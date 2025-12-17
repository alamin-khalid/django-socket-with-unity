from .models import UnityServer, Planet, TaskHistory
from .redis_queue import get_due_maps, remove_from_queue
from .tasks import assign_job_to_server
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

def assign_available_maps():
    """
    Core service loop to assign due maps to idle servers.
    Can be called by:
    1. Periodic task (scheduler)
    2. WebSocket consumers (event-driven)
    """
    # Get maps that are due for processing
    due_map_ids = get_due_maps(limit=20)
    
    if not due_map_ids:
        # No maps waiting
        return "No due maps"
    
    # Get all idle servers ordered by load
    idle_servers = list(UnityServer.objects.filter(status='idle').order_by('total_completed_map'))
    
    if not idle_servers:
        # No servers available
        return f"No idle servers for {len(due_map_ids)} due maps"
    
    logger.info(f"Assigning maps: {len(due_map_ids)} pending, {len(idle_servers)} servers available")
    
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
            
            # Assign job
            # Note: assign_job_to_server is a shared_task.
            # If CELERY_TASK_ALWAYS_EAGER is True, it runs synchronously.
            # Otherwise it queues to a worker.
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
            
    return f"Assigned {assigned_count} maps"
