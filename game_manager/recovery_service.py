"""
Game Manager - Recovery Service
================================

Centralized module for job recovery operations. This consolidates
recovery logic that was previously duplicated across:
- startup.py (Django restart recovery)
- consumers.py (WebSocket disconnect recovery)
- tasks.py (health check recovery)

Functions
---------
- recover_orphaned_job(): Recover a single orphaned job from a server
- recover_error_planets(): Auto-recover planets stuck in error status

Author: Krada Games
Last Modified: 2024-12
"""

from django.utils import timezone
from typing import Optional
import logging

from .models import UnityServer, Planet, TaskHistory
from .redis_queue import add_planet_to_queue

logger = logging.getLogger(__name__)


def recover_orphaned_job(server: UnityServer, reason: str = "Server offline") -> Optional[str]:
    """
    Recover any orphaned job from a server.
    
    When a server goes offline (disconnect, crash, timeout), any job it was
    processing becomes "orphaned" and would be stuck forever. This function
    recovers the job by:
    
    1. Resetting planet status to 'queued'
    2. Clearing processing_server reference
    3. Re-adding to Redis queue for reassignment
    4. Updating TaskHistory with timeout status
    
    Args:
        server: The UnityServer that has an orphaned job
        reason: Description of why recovery is happening (for logs/TaskHistory)
    
    Returns:
        str: Planet ID that was recovered
        None: If server had no current task
    
    Example:
        >>> from .recovery_service import recover_orphaned_job
        >>> planet_id = recover_orphaned_job(server, "WebSocket disconnect")
        >>> if planet_id:
        ...     print(f"Recovered {planet_id}")
    """
    if not server.current_task:
        return None
    
    planet = server.current_task
    planet_id = planet.planet_id
    
    logger.info(f"[Recovery] ♻ Recovering job {planet_id} from {server.server_id}: {reason}")
    
    # --- Reset Planet State ---
    planet.status = 'queued'
    planet.processing_server = None
    planet.save(update_fields=['status', 'processing_server'])
    
    # --- Re-add to Redis Queue ---
    add_planet_to_queue(planet.planet_id, planet.next_round_time)
    
    # --- Update TaskHistory ---
    updated = TaskHistory.objects.filter(
        planet=planet,
        server=server,
        status='started'
    ).update(
        status='timeout',
        end_time=timezone.now(),
        error_message=reason
    )
    
    if updated:
        logger.debug(f"[Recovery] Updated {updated} TaskHistory record(s) to timeout")
    
    # --- Clear Server's Task Reference ---
    server.current_task = None
    server.save(update_fields=['current_task'])
    
    return planet_id


def recover_error_planets(limit: int = 20) -> int:
    """
    Auto-recover planets stuck in 'error' status.
    
    Planets enter 'error' status when they exceed max retry attempts (5).
    This function resets them for another round of processing.
    
    Recovery Steps:
    1. Reset status to 'queued'
    2. Clear error_retry_count (fresh start)
    3. Clear processing_server reference
    4. Set next_round_time to now (immediate retry)
    5. Add to Redis queue
    
    Args:
        limit: Maximum planets to recover per call (prevents overwhelming system)
    
    Returns:
        int: Number of planets recovered
    
    Called By:
        - tasks.check_server_health() (every 5 seconds via Celery Beat)
    """
    now = timezone.now()
    error_planets = Planet.objects.filter(status='error')[:limit]
    
    if not error_planets.exists():
        return 0
    
    recovered_count = 0
    
    for planet in error_planets:
        logger.info(
            f"[Recovery] Auto-recovering error planet {planet.planet_id} "
            f"(was at retry {planet.error_retry_count})"
        )
        
        planet.status = 'queued'
        planet.error_retry_count = 0
        planet.processing_server = None
        planet.next_round_time = now  # Immediate retry
        planet.save()
        
        add_planet_to_queue(planet.planet_id, planet.next_round_time)
        recovered_count += 1
    
    if recovered_count > 0:
        logger.info(f"[Recovery] Auto-recovered {recovered_count} error planets")
    
    return recovered_count
