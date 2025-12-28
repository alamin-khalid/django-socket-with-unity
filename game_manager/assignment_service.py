"""
Game Manager - Assignment Service
==================================

This module contains the core job assignment logic - the "brain" that matches
due planets with idle Unity servers. It's designed to be called from multiple
contexts (scheduler, WebSocket events) while maintaining consistency.

Design Principles
-----------------
1. Idempotent: Safe to call multiple times without side effects
2. Self-healing: Automatically recovers from Redis/DB desync
3. Race-condition safe: Marks servers busy before async task dispatch
4. Fail-safe: Errors with one planet don't block others

Assignment Algorithm
--------------------
    1. Query Redis for due planets (next_round_time <= now)
    2. If Redis empty, fall back to Django DB query (self-healing)
    3. Also recover error planets that need retry
    4. Get idle servers ordered by workload (load balancing)
    5. Match planets to servers 1:1, mark server busy immediately
    6. Dispatch Celery task for actual job handoff
    7. Remove planet from Redis queue

Load Balancing Strategy
-----------------------
Servers are ordered by total_completed_planet (ascending), so least-loaded
servers get jobs first. This provides simple but effective load distribution.

    Server A: 100 completed → lower priority
    Server B: 50 completed  → higher priority (gets next job)

Callers
-------
1. Celery Beat scheduler (process_due_planets task, every 5s)
2. WebSocket consumer on server idle status (event-driven, immediate)

Race Condition Prevention
-------------------------
The critical section between "find idle server" and "assign job" is protected:

    ┌────────────────────────────────────────────────────────────┐
    │  WRONG (race condition):                                   │
    │  1. Query idle servers                                     │
    │  2. Dispatch Celery task                    ← Task A       │
    │  3. Task A starts, marks server busy                       │
    │  ... meanwhile ...                                         │
    │  1. Query idle servers (same server!)      ← Task B        │
    │  2. Dispatch Celery task (double assign!)                  │
    └────────────────────────────────────────────────────────────┘
    
    ┌────────────────────────────────────────────────────────────┐
    │  CORRECT (our approach):                                   │
    │  1. Query idle servers                                     │
    │  2. Mark server busy IMMEDIATELY (sync, before task)       │
    │  3. Dispatch Celery task                                   │
    │  ... other calls see server as busy, skip it ...           │
    └────────────────────────────────────────────────────────────┘

Author: Krada Games
Last Modified: 2024-12
"""

from typing import List
from celery.utils.log import get_task_logger

from .models import UnityServer, Planet, TaskHistory
from .redis_queue import get_due_planets, remove_from_queue

logger = get_task_logger(__name__)


def assign_available_planets() -> str:
    """
    Core assignment logic: match due planets with idle servers.
    
    This is the main entry point for the scheduling system. It handles:
    - Querying due planets from Redis
    - Self-healing if Redis is empty but DB has queued planets
    - Recovering error planets for retry
    - Load-balanced server assignment
    - Race condition prevention
    
    Returns:
        str: Human-readable summary of actions taken
        Examples:
            "Assigned 3 planets"
            "No due planets"
            "No idle servers for 5 due planets"
    
    Self-Healing Behavior:
        If Redis queue is empty, checks Django DB for:
        1. Queued planets past their next_round_time (missed scheduling)
        2. Error planets that can be retried
        
        This handles scenarios like:
        - Redis restart losing queue data
        - Manual database changes not synced to Redis
        - Error planets needing admin retry
    
    Thread Safety:
        Safe to call concurrently from multiple processes/threads.
        Server busy status is marked synchronously before Celery dispatch.
    """
    # Lazy import to avoid circular dependency
    from .tasks import assign_job_to_server
    
    # =========================================================================
    # STEP 1: Get due planets from Redis (primary source)
    # =========================================================================
    due_planet_ids: List[str] = get_due_planets(limit=20)
    
    # =========================================================================
    # STEP 2: Self-healing - recover from Redis/DB desync
    # =========================================================================
    if not due_planet_ids:
        due_planet_ids = _recover_missed_planets()
    
    if not due_planet_ids:
        return "No due planets"
    
    # =========================================================================
    # STEP 3: Get available servers (load balanced)
    # =========================================================================
    # Order by total_completed_planet ASC = least loaded first
    idle_servers = list(
        UnityServer.objects.filter(status='idle')
        .order_by('total_completed_planet')
    )
    
    if not idle_servers:
        _log_server_statistics()
        return f"No idle servers for {len(due_planet_ids)} due planets"
    
    logger.info(
        f"Assigning planets: {len(due_planet_ids)} pending, "
        f"{len(idle_servers)} servers available"
    )
    
    # =========================================================================
    # STEP 4: Match planets to servers
    # =========================================================================
    assigned_count = 0
    
    for planet_id in due_planet_ids:
        if not idle_servers:
            logger.info("No more idle servers, stopping assignment")
            break
        
        try:
            # Verify planet exists and is in queued state
            planet_obj = Planet.objects.get(planet_id=planet_id, status='queued')
            
            # Pop next idle server (least loaded)
            server = idle_servers.pop(0)
            
            # -----------------------------------------------------------
            # CRITICAL: Mark server busy BEFORE async dispatch
            # This prevents race conditions where multiple calls
            # could assign the same server simultaneously
            # -----------------------------------------------------------
            server.status = 'busy'
            server.save(update_fields=['status'])
            
            # Dispatch actual assignment to Celery worker
            assign_job_to_server.delay(planet_obj.planet_id, server.id)
            
            # Remove from Redis queue (prevent re-processing)
            remove_from_queue(planet_id)
            
            assigned_count += 1
            logger.info(f"Assigned planet {planet_id} to server {server.server_id}")
            
        except Planet.DoesNotExist:
            # Planet was deleted or already being processed
            logger.warning(f"Planet {planet_id} not found or not queued")
            remove_from_queue(planet_id)  # Clean up stale Redis entry
            continue
            
        except Exception as e:
            logger.error(f"Error assigning planet {planet_id}: {e}")
            continue
    
    return f"Assigned {assigned_count} planets"


def _recover_missed_planets() -> List[str]:
    """
    Self-healing: recover planets that were missed by Redis.
    
    Checks the Django database for:
    1. Queued planets past their next_round_time (Redis desync)
    2. Error planets that need retry (reset and requeue)
    
    Returns:
        List[str]: Recovered planet IDs that were added to Redis queue
    
    Why is this needed?
        Redis is used as a scheduling cache, but Django DB is the source
        of truth. If Redis loses data (restart, memory pressure, etc.),
        this function ensures planets aren't permanently stuck.
    """
    from django.utils import timezone
    from .redis_queue import add_planet_to_queue
    
    recovered_ids: List[str] = []
    
    # --- Recover queued planets missing from Redis ---
    missed_planets = Planet.objects.filter(
        status='queued',
        next_round_time__lte=timezone.now()
    ).order_by('next_round_time')[:20]
    
    if missed_planets.exists():
        count = missed_planets.count()
        logger.warning(
            f"Found {count} queued planets in DB missing from Redis. Re-queueing..."
        )
        
        for planet_obj in missed_planets:
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            recovered_ids.append(planet_obj.planet_id)
        
        logger.info(f"Recovered {len(recovered_ids)} planets from DB fallback")
    
    # --- Auto-recover error planets ---
    # Planets in 'error' status have exceeded max retries (5) but we now
    # automatically reset them and re-queue for continuous processing.
    error_planets = Planet.objects.filter(status='error')[:20]
    
    if error_planets.exists():
        logger.warning(
            f"Found {error_planets.count()} planets in ERROR state. "
            f"Auto-recovering..."
        )
        
        for planet_obj in error_planets:
            # Reset to queued state
            planet_obj.status = 'queued'
            planet_obj.error_retry_count = 0
            planet_obj.processing_server = None
            planet_obj.next_round_time = timezone.now()
            planet_obj.save()
            
            # Add to Redis queue for immediate processing
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            recovered_ids.append(planet_obj.planet_id)
            
            logger.info(f"Auto-recovered error planet {planet_obj.planet_id}")
    
    return recovered_ids


def _log_server_statistics() -> None:
    """
    Log server status breakdown for debugging.
    
    Called when no idle servers are available. Helps diagnose
    capacity issues or unexpected server states.
    """
    stats = {
        'idle': UnityServer.objects.filter(status='idle').count(),
        'busy': UnityServer.objects.filter(status='busy').count(),
        'offline': UnityServer.objects.filter(status='offline').count(),
        'total': UnityServer.objects.count()
    }
    logger.debug(f"Server statistics: {stats}")
