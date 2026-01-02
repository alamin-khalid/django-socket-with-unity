"""
Game Manager - Startup Hooks
=============================

This module contains startup routines that run when Django initializes.
These functions ensure the system starts in a clean, consistent state.

Problem Solved
--------------
When Django/Daphne restarts:
- All WebSocket connections are terminated
- But database still shows servers as "idle" or "busy"
- Any in-progress jobs would be stuck in "processing" state forever

This startup hook resets the world to a known good state.

When Is This Called?
--------------------
The function is registered in apps.py ready() hook:

    class GameManagerConfig(AppConfig):
        def ready(self):
            from .startup import reset_all_servers_offline
            reset_all_servers_offline()

Important: Only runs once per Django process start, not on every request.

Recovery Logic
--------------
    1. Find all servers NOT marked offline (they're stale)
    2. If server had current_task, that job is orphaned:
       - Reset planet to 'queued' status
       - Re-add to Redis queue for reassignment
       - Mark TaskHistory as 'timeout'
    3. Mark server offline

Author: AL AMIN KHALID
Last Modified: 2024-12
"""

from django.utils import timezone
from typing import NoReturn
import logging

from .models import UnityServer, Planet, TaskHistory
from .redis_queue import add_planet_to_queue

logger = logging.getLogger(__name__)


def reset_all_servers_offline() -> None:
    """
    Reset all server states to offline on Django startup.
    
    This function ensures data consistency when Django restarts:
    - WebSocket connections don't survive process restart
    - Database state must match reality (no connections = all offline)
    - In-progress jobs must be recovered to prevent stuck planets
    
    Idempotent: Safe to call multiple times; only affects active servers.
    
    Side Effects:
        - Updates UnityServer.status to 'offline' for all non-offline servers
        - Updates Planet.status to 'queued' for orphaned processing jobs
        - Updates TaskHistory to 'timeout' for orphaned started tasks
        - Adds recovered planets to Redis queue
    
    Example Output:
        --- [Startup] Marked 3 servers offline, recovered 1 job ---
    """
    print("=" * 60)
    print("[Startup] Verifying Server States")
    print("=" * 60)
    
    # =========================================================================
    # Find Stale Servers
    # =========================================================================
    # Any server not already offline is stale after restart
    active_servers = UnityServer.objects.exclude(status='offline')
    
    if not active_servers.exists():
        print("[Startup] ✓ All servers already offline. Clean state.")
        return
    
    server_count = active_servers.count()
    recovered_jobs = 0
    
    # =========================================================================
    # Process Each Stale Server
    # =========================================================================
    for server in active_servers:
        # Check if server had an in-progress job
        if server.current_task:
            planet_obj = server.current_task
            
            print(f"[Startup] ♻ Recovering orphaned job {planet_obj.planet_id} from {server.server_id}")
            
            # --- Reset Planet State ---
            planet_obj.status = 'queued'
            planet_obj.processing_server = None
            planet_obj.save()
            
            # --- Re-add to Queue ---
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            
            # --- Update Task History ---
            # Mark the incomplete task as timed out
            updated = TaskHistory.objects.filter(
                planet=planet_obj,
                server=server,
                status='started'
            ).update(
                status='timeout',
                end_time=timezone.now(),
                error_message='Django restart - server connection lost'
            )
            
            if updated:
                logger.info(f"Marked {updated} task history record(s) as timeout")
            
            # Clear server's task reference
            server.current_task = None
            recovered_jobs += 1
        
        # --- Mark Server Offline ---
        server.status = 'offline'
        server.save()
    
    # =========================================================================
    # Summary
    # =========================================================================
    print("=" * 60)
    print(f"[Startup] Marked {server_count} servers offline, recovered {recovered_jobs} jobs")
    print("=" * 60)
    
    if recovered_jobs > 0:
        logger.info(
            f"Startup recovery: {server_count} servers reset, "
            f"{recovered_jobs} orphaned jobs requeued"
        )
