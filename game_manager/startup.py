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

Author: Krada Games
Last Modified: 2024-12
"""

import logging
from .models import UnityServer
from .recovery_service import recover_orphaned_job

logger = logging.getLogger(__name__)


def reset_all_servers_offline() -> None:
    """
    Reset all server states to offline on Django startup.
    
    This function ensures data consistency when Django restarts:
    - WebSocket connections don't survive process restart
    - Database state must match reality (no connections = all offline)
    - In-progress jobs must be recovered to prevent stuck planets
    
    Idempotent: Safe to call multiple times; only affects active servers.
    
    Example Output:
        --- [Startup] Marked 3 servers offline, recovered 1 job ---
    """
    print("=" * 60)
    print("[Startup] Verifying Server States")
    print("=" * 60)
    
    # Find all non-offline servers (they're stale after restart)
    active_servers = UnityServer.objects.exclude(status='offline')
    
    if not active_servers.exists():
        print("[Startup] ✓ All servers already offline. Clean state.")
        return
    
    server_count = active_servers.count()
    recovered_jobs = 0
    
    for server in active_servers:
        # Use centralized recovery service for orphaned jobs
        planet_id = recover_orphaned_job(server, "Django restart - server connection lost")
        if planet_id:
            print(f"[Startup] ♻ Recovered orphaned job {planet_id} from {server.server_id}")
            recovered_jobs += 1
        
        # Mark server offline
        server.status = 'offline'
        server.save(update_fields=['status'])
    
    print("=" * 60)
    print(f"[Startup] Marked {server_count} servers offline, recovered {recovered_jobs} jobs")
    print("=" * 60)
    
    if recovered_jobs > 0:
        logger.info(
            f"Startup recovery: {server_count} servers reset, "
            f"{recovered_jobs} orphaned jobs requeued"
        )
