from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from datetime import timedelta, datetime
from .models import UnityServer, Planet, TaskHistory
from .redis_queue import get_due_maps, remove_from_queue, add_map_to_queue
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

logger = get_task_logger(__name__)

@shared_task
def process_due_maps():
    """
    Main scheduling loop - runs every 5 seconds.
    Checks for due maps and assigns to idle servers.
    """
    # Get maps that are due for processing
    due_map_ids = get_due_maps(limit=20)
    
    if not due_map_ids:
        return "No due maps"
    
    logger.info(f"Found {len(due_map_ids)} due maps: {due_map_ids}")
    
    # Get idle servers ordered by total jobs completed (load balancing)
    idle_servers = list(UnityServer.objects.filter(status='idle').order_by('total_completed_map'))
    
    if not idle_servers:
        logger.warning(f"No idle servers available for {len(due_map_ids)} due maps")
        return f"No idle servers for {len(due_map_ids)} due maps"
    
    assigned_count = 0
    
    for map_id in due_map_ids:
        if not idle_servers:
            logger.info("No more idle servers, stopping assignment")
            break
            
        try:
            # Get map object - must be in 'queued' status
            map_obj = Planet.objects.get(map_id=map_id, status='queued')
            
            # Get next idle server
            server = idle_servers.pop(0)
            
            # Assign job asynchronously
            assign_job_to_server.delay(map_obj.map_id, server.id)
            
            # Remove from Redis queue
            remove_from_queue(map_id)
            
            assigned_count += 1
            logger.info(f"Assigned map {map_id} to server {server.server_id}")
                
        except Planet.DoesNotExist:
            # Map was deleted or already processing
            logger.warning(f"Map {map_id} not found or not queued, removing from queue")
            remove_from_queue(map_id)
            continue
        except Exception as e:
            logger.error(f"Error assigning map {map_id}: {e}")
            continue
    
    return f"Assigned {assigned_count}/{len(due_map_ids)} maps to servers"

@shared_task
def assign_job_to_server(map_id: str, server_id: int):
    """
    Assign specific map to specific server via WebSocket.
    
    Args:
        map_id: Map identifier (string)
        server_id: UnityServer database ID (integer)
    """
    try:
        map_obj = Planet.objects.get(map_id=map_id)
        server = UnityServer.objects.get(id=server_id)
        
        logger.info(f"Assigning map {map_id} to server {server.server_id}")
        
        # Update map status
        map_obj.status = 'processing'
        map_obj.processing_server = server
        map_obj.save()
        
        # Update server status
        server.status = 'busy'
        server.current_task = map_obj
        server.save()
        
        # Create task history record
        TaskHistory.objects.create(
            map=map_obj,
            server=server,
            status='started'
        )
        
        # Send job via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'server_{server.server_id}',
            {
                'type': 'job_assignment',
                'map_id': map_obj.map_id,
                'round_id': map_obj.round_id,
                'season_id': map_obj.season_id,
            }
        )
        
        logger.info(f"Job assigned: {map_id} → {server.server_id}")
        return True
        
    except Planet.DoesNotExist:
        logger.error(f"Map {map_id} not found")
        return False
    except UnityServer.DoesNotExist:
        logger.error(f"Server with ID {server_id} not found")
        return False
    except Exception as e:
        logger.error(f"Job assignment failed: {e}")
        return False

@shared_task
def handle_job_completion(map_id: str, server_id: str, result_data: dict, next_time_seconds: int):
    """
    Process completed job from Unity.
    - Update map status
    - Free up server
    - Requeue map for next round
    
    Args:
        map_id: Map identifier
        server_id: Server identifier (string, not DB ID)
        result_data: Results from Unity calculation
        next_time_seconds: Seconds until next round
    """
    try:
        map_obj = Planet.objects.get(map_id=map_id)
        server = UnityServer.objects.get(server_id=server_id)
        
        logger.info(f"Processing job completion: {map_id} from {server_id}")
        
        # Calculate next round time
        next_round_time = timezone.now() + timedelta(seconds=next_time_seconds)
        
        # Update map
        map_obj.status = 'queued'
        map_obj.round_id += 1
        map_obj.next_round_time = next_round_time
        map_obj.last_processed = timezone.now()
        map_obj.processing_server = None
        map_obj.save()
        
        # Free server
        server.status = 'idle'
        server.current_task = None
        server.total_completed_map += 1
        server.save()
        
        # Update task history
        task_history = TaskHistory.objects.filter(
            map=map_obj,
            server=server,
            status='started'
        ).order_by('-start_time').first()
        
        if task_history:
            task_history.status = 'completed'
            task_history.end_time = timezone.now()
            task_history.result_data = result_data
            duration = (task_history.end_time - task_history.start_time).total_seconds()
            task_history.duration_seconds = duration
            task_history.save()
            logger.info(f"Task history updated: {duration:.2f}s")
        
        # Requeue for next round
        add_map_to_queue(map_obj.map_id, next_round_time)
        
        logger.info(f"Map {map_id} completed, round {map_obj.round_id}, next at {next_round_time}")
        return f"Map {map_id} completed and requeued for {next_round_time}"
        
    except Planet.DoesNotExist:
        logger.error(f"Map {map_id} not found during completion")
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
            map_obj = server.current_task
            logger.info(f"Recovering job {map_obj.map_id} from offline server {server.server_id}")
            
            # Reset map to queued
            map_obj.status = 'queued'
            map_obj.processing_server = None
            map_obj.save()
            
            # Re-add to queue
            add_map_to_queue(map_obj.map_id, map_obj.next_round_time)
            
            # Mark task history as failed/timeout
            TaskHistory.objects.filter(
                map=map_obj,
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
def handle_job_error(map_id: str, server_id: str, error_message: str):
    """
    Handle job errors reported by Unity servers.
    
    Args:
        map_id: Map identifier
        server_id: Server identifier
        error_message: Error description
    """
    try:
        map_obj = Planet.objects.get(map_id=map_id)
        server = UnityServer.objects.get(server_id=server_id)
        
        logger.error(f"Job error: {map_id} on {server_id}: {error_message}")
        
        # Update map status
        map_obj.status = 'error'
        map_obj.processing_server = None
        map_obj.save()
        
        # Free server
        server.status = 'idle'
        server.current_task = None
        server.save()
        
        # Update task history
        task_history = TaskHistory.objects.filter(
            map=map_obj,
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
        
        logger.info(f"Job error handled for {map_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error handling job error: {e}")
        return False
