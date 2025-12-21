from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from datetime import timedelta, datetime
from .models import UnityServer, Planet, TaskHistory
from .redis_queue import get_due_planets, remove_from_queue, add_planet_to_queue
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

logger = get_task_logger(__name__)

@shared_task
def process_due_planets():
    """
    Main scheduling loop - runs every 5 seconds.
    Checks for due planets and assigns to idle servers.
    """
    from .assignment_service import assign_available_planets
    return assign_available_planets()

@shared_task
def assign_job_to_server(planet_id: str, server_id: int):
    """
    Assign specific planet to specific server via WebSocket.
    
    Args:
        planet_id: Planet identifier (string)
        server_id: UnityServer database ID (integer)
    """
    try:
        planet_obj = Planet.objects.get(planet_id=planet_id)
        server = UnityServer.objects.get(id=server_id)
        
        logger.info(f"Assigning planet {planet_id} to server {server.server_id}")
        
        # Update planet status
        planet_obj.status = 'processing'
        planet_obj.processing_server = server
        planet_obj.save()
        
        # Update server status
        server.status = 'busy'
        server.current_task = planet_obj
        server.save()
        
        # Create task history record
        TaskHistory.objects.create(
            planet=planet_obj,
            server=server,
            status='started'
        )
        
        # Send job via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'server_{server.server_id}',
            {
                'type': 'job_assignment',
                'planet_id': planet_obj.planet_id,
                'round_id': planet_obj.round_id,
                'season_id': planet_obj.season_id,
            }
        )
        
        logger.info(f"Job assigned: {planet_id} → {server.server_id}")
        return True
        
    except Planet.DoesNotExist:
        logger.error(f"Planet {planet_id} not found")
        return False
    except UnityServer.DoesNotExist:
        logger.error(f"Server with ID {server_id} not found")
        return False
    except Exception as e:
        logger.error(f"Job assignment failed: {e}")
        return False

@shared_task
def handle_job_completion(planet_id: str, server_id: str, next_round_time_str: str):
    """
    Process completed job from Unity.
    - Update planet status
    - Free up server
    - Requeue planet for next round
    
    Args:
        planet_id: Planet identifier
        server_id: Server identifier (string, not DB ID)
        next_round_time_str: ISO 8601 datetime string for next round
    """
    from dateutil import parser
    
    try:
        planet_obj = Planet.objects.get(planet_id=planet_id)
        server = UnityServer.objects.get(server_id=server_id)
        
        logger.info(f"Processing job completion: {planet_id} from {server_id}")
        
        # Parse next round time from ISO string
        next_round_time = parser.isoparse(next_round_time_str)
        
        # Update planet
        planet_obj.status = 'queued'
        planet_obj.round_id += 1
        planet_obj.next_round_time = next_round_time
        planet_obj.last_processed = timezone.now()
        planet_obj.processing_server = None
        planet_obj.save()
        
        # Free server
        server.status = 'idle'
        server.current_task = None
        server.total_completed_planet += 1
        server.save()
        
        # Update task history
        task_history = TaskHistory.objects.filter(
            planet=planet_obj,
            server=server,
            status='started'
        ).order_by('-start_time').first()
        
        if task_history:
            task_history.status = 'completed'
            task_history.end_time = timezone.now()
            duration = (task_history.end_time - task_history.start_time).total_seconds()
            task_history.duration_seconds = duration
            task_history.save()
            logger.info(f"Task history updated: {duration:.2f}s")
        
        # Requeue for next round
        add_planet_to_queue(planet_obj.planet_id, next_round_time)
        
        logger.info(f"Planet {planet_id} completed, round {planet_obj.round_id}, next at {next_round_time}")
        return f"Planet {planet_id} completed and requeued for {next_round_time}"
        
    except Planet.DoesNotExist:
        logger.error(f"Planet {planet_id} not found during completion")
        return False
    except UnityServer.DoesNotExist:
        logger.error(f"Server {server_id} not found during completion")
        return False
    except Exception as e:
        logger.error(f"Job completion handling failed: {e}")
        return False

@shared_task
def check_server_health():
    """
    Mark servers offline if no heartbeat for 30+ seconds.
    Recover stuck jobs.
    """
    threshold = timezone.now() - timedelta(seconds=30)
    
    # Find stale servers (idle or busy but no recent heartbeat)
    stale_servers = UnityServer.objects.filter(
        status__in=['idle', 'busy'],
        last_heartbeat__lt=threshold
    )
    
    recovered_jobs = 0
    
    for server in stale_servers:
        logger.warning(f"Server {server.server_id} detected as stale (last heartbeat: {server.last_heartbeat})")
        
        # Mark offline
        server.status = 'offline'
        
        # If had a job, recover it
        if server.current_task:
            planet_obj = server.current_task
            logger.info(f"Recovering job {planet_obj.planet_id} from offline server {server.server_id}")
            
            # Reset planet to queued
            planet_obj.status = 'queued'
            planet_obj.processing_server = None
            planet_obj.save()
            
            # Re-add to queue
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            
            # Mark task history as failed/timeout
            TaskHistory.objects.filter(
                planet=planet_obj,
                server=server,
                status='started'
            ).update(
                status='timeout',
                end_time=timezone.now(),
                error_message='Server went offline during processing'
            )
            
            recovered_jobs += 1
        
        server.current_task = None
        server.save()
    
    if stale_servers.exists():
        logger.warning(f"Marked {stale_servers.count()} servers offline, recovered {recovered_jobs} jobs")
        return f"Marked {stale_servers.count()} servers offline, recovered {recovered_jobs} jobs"
    
    return "All servers healthy"

@shared_task
def handle_job_error(planet_id: str, server_id: str, error_message: str):
    """
    Handle job errors reported by Unity servers.
    
    Args:
        planet_id: Planet identifier
        server_id: Server identifier
        error_message: Error description
    """
    try:
        planet_obj = Planet.objects.get(planet_id=planet_id)
        server = UnityServer.objects.get(server_id=server_id)
        
        logger.error(f"Job error: {planet_id} on {server_id}: {error_message}")
        
        # Update planet status
        planet_obj.status = 'error'
        planet_obj.processing_server = None
        planet_obj.save()
        
        # Free server
        server.status = 'idle'
        server.current_task = None
        server.total_failed_planet += 1  # Increment failed counter
        server.save()
        
        # Update task history
        task_history = TaskHistory.objects.filter(
            planet=planet_obj,
            server=server,
            status='started'
        ).order_by('-start_time').first()
        
        if task_history:
            task_history.status = 'failed'
            task_history.end_time = timezone.now()
            task_history.error_message = error_message
            duration = (task_history.end_time - task_history.start_time).total_seconds()
            task_history.duration_seconds = duration
            task_history.save()
        
        logger.info(f"Job error handled for {planet_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error handling job error: {e}")
        return False
