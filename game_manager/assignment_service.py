from .models import UnityServer, Planet, TaskHistory
from .redis_queue import get_due_planets, remove_from_queue
from .tasks import assign_job_to_server
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

def assign_available_planets():
    """
    Core service loop to assign due planets to idle servers.
    Can be called by:
    1. Periodic task (scheduler)
    2. WebSocket consumers (event-driven)
    """
    # Get planets that are due for processing
    due_planet_ids = get_due_planets(limit=20)
    
    # --- QUEUE RECOVERY / SELF-HEALING ---
    # If Redis queue is empty, check if we have "queued" planets in DB that were missed
    # (e.g. due to Redis restart or desync)
    if not due_planet_ids:
        from django.utils import timezone
        # Check for planets that should be processed (queued and time passed)
        missed_planets = Planet.objects.filter(
            status='queued', 
            next_round_time__lte=timezone.now()
        ).order_by('next_round_time')[:20]
        
        if missed_planets.exists():
            from .redis_queue import add_planet_to_queue
            logger.warning(f"Found {missed_planets.count()} queued planets in DB missing from Redis. Re-queueing...")
            
            for planet_obj in missed_planets:
                add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
                due_planet_ids.append(planet_obj.planet_id)
            
            logger.info(f"Recovered {len(due_planet_ids)} planets from DB fallback")

    if not due_planet_ids:
        # No planets waiting
        return "No due planets"
    
    # Get all idle servers ordered by load
    idle_servers = list(UnityServer.objects.filter(status='idle').order_by('total_completed_planet'))
    
    if not idle_servers:
        # Debug: Why no servers? (only log at debug level to avoid spam)
        all_counts = {
            'idle': UnityServer.objects.filter(status='idle').count(),
            'busy': UnityServer.objects.filter(status='busy').count(),
            'offline': UnityServer.objects.filter(status='offline').count(),
            'total': UnityServer.objects.count()
        }
        logger.debug(f"No idle servers. Stats: {all_counts}")
        
        # No servers available
        return f"No idle servers for {len(due_planet_ids)} due planets"
    
    logger.info(f"Assigning planets: {len(due_planet_ids)} pending, {len(idle_servers)} servers available")
    
    assigned_count = 0
    
    for planet_id in due_planet_ids:
        if not idle_servers:
            logger.info("No more idle servers, stopping assignment")
            break
            
        try:
            # Get planet object - must be in 'queued' status
            planet_obj = Planet.objects.get(planet_id=planet_id, status='queued')
            
            # Get next idle server
            server = idle_servers.pop(0)
            
            # IMPORTANT: Mark server busy IMMEDIATELY to prevent race condition
            # (before Celery task runs, another call could assign same server)
            server.status = 'busy'
            server.save(update_fields=['status'])
            
            # Assign job (runs immediately in eager mode, async otherwise)
            assign_job_to_server.delay(planet_obj.planet_id, server.id)
            
            # Remove from Redis queue
            remove_from_queue(planet_id)
            
            assigned_count += 1
            logger.info(f"Assigned planet {planet_id} to server {server.server_id}")
                
        except Planet.DoesNotExist:
            logger.warning(f"Planet {planet_id} not found or not queued")
            remove_from_queue(planet_id)
            continue
        except Exception as e:
            logger.error(f"Error assigning planet {planet_id}: {e}")
            continue
            
    return f"Assigned {assigned_count} planets"
