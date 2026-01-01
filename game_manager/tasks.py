"""
Game Manager - Celery Task Definitions
======================================

This module defines asynchronous Celery tasks for the game server orchestration system.
These tasks handle the core job lifecycle: scheduling, assignment, completion, and error recovery.

Architecture Overview
---------------------
The system uses a producer-consumer pattern where:
- Redis sorted set acts as a priority queue (sorted by next_round_time)
- Celery Beat scheduler triggers periodic checks every 5 seconds
- WebSocket channels push jobs to Unity game servers in real-time

Task Flow
---------
1. process_due_planets() - Periodic scheduler finds planets ready for processing
2. assign_job_to_server() - Dispatches job to specific Unity server via WebSocket
3. handle_job_completion() - Processes successful job results from Unity
4. handle_job_error() - Handles failures with retry logic (max 5 attempts)
5. check_server_health() - Monitors server heartbeats, recovers orphaned jobs

Key Design Decisions
--------------------
- Single TaskHistory record per job attempt (retries update existing record)
- Immediate retry on failure (no backoff delay) with max 5 retry limit
- Server state transitions: offline -> idle -> busy -> idle (on completion)
- Planet state transitions: queued -> processing -> queued (on completion)

Author: Krada Games
Last Modified: 2024-12
"""

from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from datetime import timedelta, datetime
from typing import Optional, Union

from .models import UnityServer, Planet, TaskHistory
from .redis_queue import get_due_planets, remove_from_queue, add_planet_to_queue
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# Celery task logger - outputs to Celery worker logs
logger = get_task_logger(__name__)


# =============================================================================
# SCHEDULING TASKS
# =============================================================================

@shared_task
def process_due_planets() -> str:
    """
    Main scheduling loop - triggered by Celery Beat every 5 seconds.
    
    Queries Redis for planets whose next_round_time has passed and assigns
    them to available idle Unity servers. This is the entry point for the
    entire job processing pipeline.
    
    Returns:
        str: Summary of assignments made (e.g., "Assigned 3 planets to servers")
    
    Note:
        Actual assignment logic is delegated to assignment_service module
        to keep this task lightweight and testable.
    """
    from .assignment_service import assign_available_planets
    return assign_available_planets()


# =============================================================================
# JOB ASSIGNMENT
# =============================================================================

@shared_task
def assign_job_to_server(planet_id: str, server_id: int) -> bool:
    """
    Assign a specific planet calculation job to a Unity game server.
    
    This task is responsible for the complete job handoff:
    1. Updates planet status to 'processing'
    2. Marks server as 'busy' with current task
    3. Creates/reuses TaskHistory record for tracking
    4. Sends job details to Unity via WebSocket channel
    
    Args:
        planet_id: Unique planet identifier (string, e.g., "79001")
        server_id: UnityServer database primary key (integer)
    
    Returns:
        bool: True if assignment successful, False otherwise
    
    TaskHistory Strategy:
        - Fresh job (retry_count=0): Creates new TaskHistory record
        - Retry attempt (retry_count>0): Reuses existing failed record
        This prevents database bloat from rapid retry cycles.
    
    WebSocket Message Format:
        {
            'type': 'job_assignment',
            'planet_id': '79001',
            'round_id': 65,
            'season_id': 42
        }
    
    Raises:
        Does not raise - catches all exceptions and logs errors.
    """
    try:
        planet_obj = Planet.objects.get(planet_id=planet_id)
        server = UnityServer.objects.get(id=server_id)
        
        logger.info(f"Assigning planet {planet_id} to server {server.server_id}")
        
        # --- State Transition: Planet ---
        # queued -> processing
        planet_obj.status = 'processing'
        planet_obj.processing_server = server
        planet_obj.save()
        
        # --- State Transition: Server ---
        # idle -> busy
        server.status = 'busy'
        server.current_task = planet_obj
        server.save()
        
        # --- TaskHistory Management ---
        # Retry jobs reuse existing record to prevent database bloat
        if planet_obj.error_retry_count > 0:
            existing_task = TaskHistory.objects.filter(
                planet=planet_obj,
                status='failed'
            ).order_by('-start_time').first()
            
            if existing_task:
                # Reset existing record for retry attempt
                existing_task.server = server
                existing_task.status = 'started'
                existing_task.start_time = timezone.now()
                existing_task.end_time = None
                existing_task.duration_seconds = None
                # Preserve error_message to maintain retry history
                existing_task.save()
            else:
                # Fallback: create new record if none found
                TaskHistory.objects.create(
                    planet=planet_obj,
                    server=server,
                    status='started'
                )
        else:
            # Fresh job - create new tracking record
            TaskHistory.objects.create(
                planet=planet_obj,
                server=server,
                status='started'
            )
        
        # --- WebSocket Dispatch ---
        # Send job to Unity server via Django Channels
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


# =============================================================================
# JOB COMPLETION
# =============================================================================

@shared_task
def handle_job_completion(
    planet_id: str,
    server_id: str,
    next_round_time_str: str,
    season_id: Optional[int] = None,
    round_id: Optional[int] = None,
    current_round_number: Optional[int] = None
) -> Union[str, bool]:
    """
    Process successful job completion reported by Unity server.
    
    This is the happy path - Unity has successfully calculated the planet round
    and is reporting back the results along with the next scheduled time.
    
    Responsibilities:
    1. Parse and validate next_round_time from ISO 8601 string
    2. Update planet state with new round data from Unity
    3. Reset error_retry_count (successful = clean slate)
    4. Free up the server for new assignments
    5. Update TaskHistory with completion status and duration
    6. Requeue planet to Redis for next round
    
    Args:
        planet_id: Planet that was processed
        server_id: Server that completed the job (string identifier, not DB ID)
        next_round_time_str: When to process next round (ISO 8601 format)
        season_id: Optional - current season from Unity (trusted source)
        round_id: Optional - current round ID from Unity
        current_round_number: Optional - running count of rounds
    
    Returns:
        str: Success message with requeue time
        bool: False on any error
    
    Data Trust Model:
        Unity is the authoritative source for game state. When Unity provides
        season_id, round_id, or current_round_number, we accept those values.
        This prevents desync between Django orchestrator and Unity game state.
    """
    from dateutil import parser
    
    try:
        planet_obj = Planet.objects.get(planet_id=planet_id)
        server = UnityServer.objects.get(server_id=server_id)
        
        logger.info(f"Processing job completion: {planet_id} from {server_id}")
        
        # --- Parse Next Round Time ---
        next_round_time = parser.isoparse(next_round_time_str)
        
        # Ensure timezone awareness
        if next_round_time.tzinfo is None:
            from datetime import timezone as dt_timezone
            next_round_time = next_round_time.replace(tzinfo=dt_timezone.utc)
        
        # --- Defensive: Handle past times ---
        # If the received next_round_time is in the past (e.g., API returned
        # roundEndTime that already passed during calculation), adjust to
        # current time so it's immediately picked up by the scheduler.
        now = timezone.now()
        if next_round_time <= now:
            logger.warning(
                f"next_round_time {next_round_time} is in the past, "
                f"scheduling immediately at {now}"
            )
            next_round_time = now
        
        # --- Update Planet State ---
        planet_obj.status = 'queued'
        
        # Accept Unity-provided values as authoritative when available
        if round_id is not None:
            planet_obj.round_id = round_id
        else:
            planet_obj.round_id += 1  # Fallback: increment locally
            
        if current_round_number is not None:
            planet_obj.current_round_number = current_round_number
            
        if season_id is not None:
            planet_obj.season_id = season_id
            
        planet_obj.next_round_time = next_round_time
        planet_obj.last_processed = timezone.now()
        planet_obj.processing_server = None
        planet_obj.error_retry_count = 0  # Reset on success - clean slate
        planet_obj.save()
        
        # --- Free Server ---
        server.status = 'idle'
        server.current_task = None
        server.total_completed_planet += 1
        server.save()
        
        # --- Update TaskHistory ---
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
        
        # --- Requeue for Next Round ---
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


# =============================================================================
# HEALTH MONITORING
# =============================================================================

@shared_task
def check_server_health() -> str:
    """
    Monitor server health and recover orphaned jobs.
    
    Triggered periodically by Celery Beat. Detects servers that have stopped
    sending heartbeats (likely crashed or disconnected) and performs cleanup:
    
    1. Identify "stale" servers (no heartbeat in 30+ seconds)
    2. Mark them as offline
    3. Recover any in-progress jobs back to the queue
    4. Update TaskHistory to reflect timeout
    
    Returns:
        str: Summary of actions taken (e.g., "Marked 2 servers offline, recovered 1 job")
    
    Stale Detection Logic:
        - Only checks servers in 'idle' or 'busy' status
        - 30 second threshold balances responsiveness vs false positives
        - Heartbeats are sent by Unity every 10 seconds normally
    
    Job Recovery:
        When a busy server goes offline mid-job, the planet would be stuck in
        'processing' state forever without recovery. This task requeues it
        so another healthy server can pick it up.
    """
    HEARTBEAT_TIMEOUT_SECONDS = 30
    threshold = timezone.now() - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
    
    # Find servers that should be alive but haven't checked in
    stale_servers = UnityServer.objects.filter(
        status__in=['idle', 'busy'],
        last_heartbeat__lt=threshold
    )
    
    recovered_jobs = 0
    
    for server in stale_servers:
        logger.warning(
            f"Server {server.server_id} detected as stale "
            f"(last heartbeat: {server.last_heartbeat})"
        )
        
        # Mark offline
        server.status = 'offline'
        
        # Recover orphaned job if server was processing one
        if server.current_task:
            planet_obj = server.current_task
            logger.info(
                f"Recovering job {planet_obj.planet_id} from offline server {server.server_id}"
            )
            
            # Reset planet to queued state
            planet_obj.status = 'queued'
            planet_obj.processing_server = None
            planet_obj.save()
            
            # Re-add to Redis queue for reassignment
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            
            # Record timeout in TaskHistory
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
        count = stale_servers.count()
        logger.warning(f"Marked {count} servers offline, recovered {recovered_jobs} jobs")
        result = f"Marked {count} servers offline, recovered {recovered_jobs} jobs"
    else:
        result = "All servers healthy"
    
    # --- Auto-recover errored planets ---
    # Planets stuck in 'error' status are automatically reset and requeued
    errored_planets = Planet.objects.filter(status='error')
    recovered_errored = 0
    
    for planet_obj in errored_planets:
        logger.info(
            f"Auto-recovering errored planet {planet_obj.planet_id} "
            f"(was at retry {planet_obj.error_retry_count})"
        )
        planet_obj.status = 'queued'
        planet_obj.error_retry_count = 0
        planet_obj.processing_server = None
        planet_obj.next_round_time = timezone.now()  # Immediate retry
        planet_obj.save()
        
        add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
        recovered_errored += 1
    
    if recovered_errored > 0:
        logger.info(f"Auto-recovered {recovered_errored} errored planets")
        result += f", recovered {recovered_errored} errored planets"
    
    return result


# =============================================================================
# ERROR HANDLING
# =============================================================================

@shared_task
def handle_job_error(planet_id: str, server_id: str, error_message: str) -> Union[str, bool]:
    """
    Handle job failure reported by Unity server.
    
    Implements a retry strategy with the following characteristics:
    - Immediate retry (no backoff delay) - get back in queue ASAP
    - Maximum 5 retry attempts - prevent infinite loops
    - Single TaskHistory record per job (reused across retries)
    
    Args:
        planet_id: Planet that failed processing
        server_id: Server that reported the error
        error_message: Error details from Unity (e.g., "System busy")
    
    Returns:
        str: Status message indicating retry queued or max retries exceeded
        bool: False on exception
    
    Retry Strategy:
        The system uses immediate retry because:
        1. Errors are often transient (server busy, temporary resource issue)
        2. With single TaskHistory record, no database bloat from retries
        3. Max retry limit prevents infinite loops for persistent errors
    
    After MAX_RETRIES:
        Planet is marked with status='error' and NOT requeued.
        Requires manual intervention via admin dashboard to reset.
    
    Error Message Format:
        TaskHistory stores formatted message: "[Retry 3/5] Original error message"
        This provides visibility into retry history within single record.
    """
    MAX_RETRIES = 5
    
    try:
        planet_obj = Planet.objects.get(planet_id=planet_id)
        server = UnityServer.objects.get(server_id=server_id)
        
        # Track retry attempts
        planet_obj.error_retry_count += 1
        retry_count = planet_obj.error_retry_count
        
        logger.error(
            f"Job error: {planet_id} on {server_id} "
            f"(retry {retry_count}/{MAX_RETRIES}): {error_message}"
        )
        
        # --- Update TaskHistory ---
        task_history = TaskHistory.objects.filter(
            planet=planet_obj,
            server=server,
            status='started'
        ).order_by('-start_time').first()
        
        if task_history:
            task_history.status = 'failed'
            task_history.end_time = timezone.now()
            task_history.error_message = f"[Retry {retry_count}/{MAX_RETRIES}] {error_message}"
            duration = (task_history.end_time - task_history.start_time).total_seconds()
            task_history.duration_seconds = duration
            task_history.save()
        
        # --- Free Server ---
        server.status = 'idle'
        server.current_task = None
        server.total_failed_planet += 1
        server.save()
        
        # --- Check Retry Limit ---
        if retry_count >= MAX_RETRIES:
            # Auto-reset and requeue with cooldown instead of staying in error state
            COOLDOWN_SECONDS = 30
            logger.warning(
                f"Planet {planet_id} exceeded max retries ({MAX_RETRIES}), "
                f"auto-resetting and re-queueing with {COOLDOWN_SECONDS}s cooldown"
            )
            planet_obj.status = 'queued'
            planet_obj.processing_server = None
            planet_obj.error_retry_count = 0  # Reset retry counter
            planet_obj.next_round_time = timezone.now() + timedelta(seconds=COOLDOWN_SECONDS)
            planet_obj.save()
            
            # Add back to Redis queue with cooldown delay
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            
            return f"Planet {planet_id} auto-reset after max retries, requeued with {COOLDOWN_SECONDS}s cooldown"
        
        # --- Immediate Retry ---
        planet_obj.status = 'queued'
        planet_obj.processing_server = None
        planet_obj.next_round_time = timezone.now()  # Immediate retry
        planet_obj.save()
        
        # Add back to Redis queue
        add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
        
        logger.info(f"Job error handled for {planet_id} - retry {retry_count} queued immediately")
        return f"Planet {planet_id} retry {retry_count} queued"
        
    except Exception as e:
        logger.error(f"Error handling job error: {e}")
        return False


# =============================================================================
# UTILITY TASKS
# =============================================================================

@shared_task
def reset_planet_retry_count(planet_id: str) -> None:
    """
    Reset error retry counter for a planet.
    
    Utility task that can be called to manually reset a planet's retry count.
    Typically used after manual intervention when a planet was stuck in error state.
    
    Args:
        planet_id: Planet to reset
    
    Note:
        This is automatically done by handle_job_completion on success.
        Manual invocation is for admin recovery scenarios.
    """
    try:
        Planet.objects.filter(planet_id=planet_id).update(error_retry_count=0)
    except Exception as e:
        logger.warning(f"Could not reset retry count for {planet_id}: {e}")
