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
    
    # --- QUEUE RECOVERY / SELF-HEALING ---
    # If Redis queue is empty, check if we have "queued" maps in DB that were missed
    # (e.g. due to Redis restart or desync)
    if not due_map_ids:
        from django.utils import timezone
        # Check for maps that should be processed (queued and time passed)
        missed_maps = Planet.objects.filter(
            status='queued', 
            next_round_time__lte=timezone.now()
        ).order_by('next_round_time')[:20]
        
        if missed_maps.exists():
            from .redis_queue import add_map_to_queue
            logger.warning(f"Found {missed_maps.count()} queued maps in DB missing from Redis. Re-queueing...")
            
            for map_obj in missed_maps:
                add_map_to_queue(map_obj.map_id, map_obj.next_round_time)
                due_map_ids.append(map_obj.map_id)
            
            logger.info(f"Recovered {len(due_map_ids)} maps from DB fallback")

    if not due_map_ids:
        # No maps waiting
        return "No due maps"
    
    # Get all idle servers ordered by load
    idle_servers = list(UnityServer.objects.filter(status='idle').order_by('total_completed_map'))
    
    if not idle_servers:
        # Debug: Why no servers?
        all_counts = {
            'idle': UnityServer.objects.filter(status='idle').count(),
            'busy': UnityServer.objects.filter(status='busy').count(),
            'offline': UnityServer.objects.filter(status='offline').count(),
            'total': UnityServer.objects.count()
        }
        logger.warning(f"No idle servers! Stats: {all_counts}")
        
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
            
            # Assign job (runs immediately in eager mode)
            assign_job_to_server.delay(map_obj.map_id, server.id)
            
            # Remove from Redis queue
            remove_from_queue(map_id)
            
            assigned_count += 1
            logger.info(f"Assigned map {map_id} to server {server.server_id}")
                
        except Planet.DoesNotExist:
            logger.warning(f"Map {map_id} not found or not queued")
            remove_from_queue(map_id)
            continue
        except Exception as e:
            logger.error(f"Error assigning map {map_id}: {e}")
            continue
            
    return f"Assigned {assigned_count} maps"
