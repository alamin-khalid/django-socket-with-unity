from django.utils import timezone
from .models import UnityServer, Planet, TaskHistory
from .redis_queue import add_planet_to_queue

def reset_all_servers_offline():
    """
    Called on Django startup.
    Marks all servers as offline (since WebSocket connections are dropped on restart).
    Recovers any jobs that were in 'processing' state.
    """
    print("--- [Startup] Verifying Server States ---")
    
    # 1. Find all servers that are NOT offline
    active_servers = UnityServer.objects.exclude(status='offline')
    
    if not active_servers.exists():
        print("--- [Startup] No active servers found. Clean state. ---")
        return

    count = active_servers.count()
    recovered_jobs = 0
    
    for server in active_servers:
        # Check if server had a task
        if server.current_task:
            planet_obj = server.current_task
            print(f"--- [Startup] Recovering job {planet_obj.planet_id} from {server.server_id}")
            
            # Reset planet to queued
            planet_obj.status = 'queued'
            planet_obj.processing_server = None
            planet_obj.save()
            
            # Re-add to queue
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            
            # Update history
            TaskHistory.objects.filter(
                planet=planet_obj,
                server=server,
                status='started'
            ).update(
                status='timeout',
                end_time=timezone.now(),
                error_message='Server restart recovery'
            )
            
            server.current_task = None
            recovered_jobs += 1
            
        # Mark server offline
        server.status = 'offline'
        server.save()
        
    print(f"--- [Startup] Marked {count} servers offline, recovered {recovered_jobs} jobs ---")

