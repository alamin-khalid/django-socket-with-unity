"""
Game Manager - Django Models
============================

This module defines the core data models for the game server orchestration system.
These models represent the state of Unity game servers, planets awaiting processing,
and the historical record of all job executions.

Entity Relationship
-------------------
    UnityServer 1 ──── N TaskHistory
         │
         │ current_task (FK)
         ▼
       Planet 1 ──── N TaskHistory

Model Responsibilities
----------------------
- UnityServer: Tracks connection state, health metrics, and workload of Unity clients
- Planet: Represents a game world that requires periodic round calculations
- TaskHistory: Audit log of all job assignments with timing and outcome data

State Machines
--------------
UnityServer Status Flow:
    offline → idle → busy → idle (on completion)
                  ↓
              offline (on disconnect/timeout)

Planet Status Flow:
    queued → processing → queued (success, requeued for next round)
                       ↓
                    error (max retries exceeded)

Author: AL AMIN KHALID
Last Modified: 2024-12
"""

from django.db import models
from django.utils import timezone


class UnityServer(models.Model):
    """
    Represents a Unity game server instance connected via WebSocket.
    
    Each Unity client registers with a unique server_id and maintains
    a persistent WebSocket connection. The orchestrator tracks health
    via periodic heartbeats and assigns planet calculation jobs.
    
    Attributes:
        server_id: Unique identifier assigned by Unity client (e.g., "unity-server-1")
        server_ip: IP address of the connected Unity instance
        status: Current operational state (see STATUS_CHOICES)
        last_heartbeat: Timestamp of most recent heartbeat message
        
    Resource Metrics (updated via heartbeat):
        idle_cpu_usage: CPU % when server is idle (baseline)
        idle_ram_usage: RAM % when server is idle (baseline)
        max_cpu_usage: Peak CPU % during job processing
        max_ram_usage: Peak RAM % during job processing
        disk_usage: Current disk utilization %
        
    Work Tracking:
        current_task: Planet currently being processed (None if idle)
        total_assigned_planet: Cumulative jobs assigned to this server
        total_completed_planet: Cumulative successful completions
        total_failed_planet: Cumulative failures/errors
        
    Connection Lifecycle:
        connected_at: First connection timestamp (auto-set)
        disconnected_at: Last disconnection timestamp (if applicable)
    
    State Transitions:
        offline → idle: Server connects and reports ready
        idle → busy: Job assigned to server
        busy → idle: Job completes (success or failure)
        * → offline: Server disconnects or fails heartbeat check
    """
    
    STATUS_CHOICES = [
        ('offline', 'Offline'),           # Not connected or failed heartbeat
        ('idle', 'Idle'),                 # Connected and ready for work
        ('busy', 'Busy'),                 # Currently processing a job
        ('not_responding', 'Not Responding'),  # Connected but not responding
        ('not_initialized', 'Not Initialized'),  # Connected but not yet ready
    ]

    # --- Identity ---
    server_id = models.CharField(
        max_length=100, 
        unique=True, 
        db_index=True,
        help_text="Unique identifier assigned by Unity client"
    )
    server_ip = models.CharField(
        max_length=100, 
        db_index=True,
        help_text="IP address of the Unity server"
    )

    # --- Status & Health ---
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='offline', 
        db_index=True,
        help_text="Current operational state"
    )
    last_heartbeat = models.DateTimeField(
        null=True, 
        blank=True, 
        db_index=True,
        help_text="Timestamp of most recent heartbeat"
    )

    # --- Resource Metrics ---
    # Baseline metrics (captured when idle)
    idle_cpu_usage = models.FloatField(default=0.0, help_text="CPU % when idle")
    idle_ram_usage = models.FloatField(default=0.0, help_text="RAM % when idle")
    
    # Peak metrics (captured during processing)
    max_cpu_usage = models.FloatField(default=0.0, help_text="Peak CPU % during jobs")
    max_ram_usage = models.FloatField(default=0.0, help_text="Peak RAM % during jobs")
    
    # Storage
    disk_usage = models.FloatField(default=0.0, help_text="Current disk utilization %")

    # --- Current Work ---
    current_task = models.ForeignKey(
        'Planet', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='assigned_server',
        help_text="Planet currently being processed"
    )

    # --- Connection Lifecycle ---
    connected_at = models.DateTimeField(
        auto_now_add=True,
        help_text="First connection timestamp"
    )
    disconnected_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Last disconnection timestamp"
    )

    # --- Cumulative Statistics ---
    total_assigned_planet = models.IntegerField(
        default=0,
        help_text="Total jobs assigned to this server"
    )
    total_completed_planet = models.IntegerField(
        default=0,
        help_text="Total successful completions"
    )
    total_failed_planet = models.IntegerField(
        default=0,
        help_text="Total failures/errors"
    )

    def mark_disconnected(self) -> None:
        """
        Mark server as disconnected.
        
        Called when WebSocket connection closes. Updates disconnection
        timestamp and sets status to offline.
        """
        self.disconnected_at = timezone.now()
        self.status = 'offline'
        self.save()

    def __str__(self) -> str:
        return f"{self.server_ip} ({self.status})"
    
    class Meta:
        verbose_name = "Unity Server"
        verbose_name_plural = "Unity Servers"


class Planet(models.Model):
    """
    Represents a game planet/world requiring periodic round calculations.
    
    Planets are the fundamental work units in the system. Each planet
    belongs to a season and progresses through rounds. The orchestrator
    schedules planet calculations based on next_round_time.
    
    Attributes:
        planet_id: Unique identifier (primary key)
        season_id: Current season the planet is in
        round_id: Current round identifier
        current_round_number: Running count of completed rounds
        next_round_time: When this planet should next be processed
        status: Current state in the processing pipeline
        
    Processing State:
        last_processed: Timestamp of most recent successful processing
        processing_server: Server currently working on this planet (if any)
        error_retry_count: Consecutive failures (reset on success)
    
    State Transitions:
        queued → processing: Job assigned to server
        processing → queued: Job completed, requeued for next round
        processing → error: Max retries exceeded (5 attempts)
    
    Scheduling:
        The scheduling system queries planets where:
        - status = 'queued'
        - next_round_time <= now
        
        A composite index on (next_round_time, status) optimizes this query.
    """
    
    STATUS_CHOICES = [
        ('queued', 'Queued'),         # Ready for processing
        ('processing', 'Processing'),  # Currently being calculated
        ('completed', 'Completed'),    # Finished (rarely used, usually requeued)
        ('error', 'Error'),            # Failed max retries, needs intervention
    ]

    # --- Identity ---
    planet_id = models.CharField(
        max_length=100, 
        primary_key=True, 
        db_index=True,
        help_text="Unique planet identifier"
    )
    
    # --- Game State ---
    season_id = models.IntegerField(
        default=1, 
        db_index=True,
        help_text="Current season"
    )
    round_id = models.IntegerField(
        default=0,
        help_text="Current round identifier"
    )
    current_round_number = models.IntegerField(
        default=0,
        help_text="Running count of completed rounds"
    )
    
    # --- Scheduling ---
    next_round_time = models.DateTimeField(
        db_index=True,
        help_text="When this planet should next be processed"
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='queued', 
        db_index=True,
        help_text="Current processing state"
    )
    
    # --- Processing State ---
    last_processed = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Timestamp of last successful processing"
    )
    processing_server = models.ForeignKey(
        UnityServer, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='processing_planets',
        help_text="Server currently processing this planet"
    )
    
    # --- Error Handling ---
    error_retry_count = models.IntegerField(
        default=0,
        help_text="Consecutive error count (reset on success, max 5)"
    )

    class Meta:
        verbose_name = "Planet"
        verbose_name_plural = "Planets"
        # Composite index for efficient scheduling queries
        indexes = [
            models.Index(
                fields=['next_round_time', 'status'],
                name='planet_schedule_idx'
            ),
        ]

    def __str__(self) -> str:
        return f"Planet {self.planet_id} - Season {self.season_id} - Round {self.round_id}"


# =============================================================================
# SIGNALS
# =============================================================================

from django.db.models.signals import pre_delete
from django.dispatch import receiver

@receiver(pre_delete, sender=Planet)
def remove_planet_from_queue_on_delete(sender, instance, **kwargs) -> None:
    """
    Remove planet from Redis queue when deleted from database.
    
    This signal ensures data consistency between Django DB and Redis.
    Without this, deleted planets could remain in the Redis queue and
    cause errors when the scheduler tries to process them.
    
    Args:
        sender: The Planet model class
        instance: The Planet instance being deleted
        **kwargs: Additional signal arguments (unused)
    """
    try:
        from .redis_queue import remove_from_queue
        remove_from_queue(instance.planet_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"Could not remove {instance.planet_id} from queue: {e}"
        )


class TaskHistory(models.Model):
    """
    Audit log of all job assignments and their outcomes.
    
    Every time a planet is assigned to a server, a TaskHistory record is
    created (or reused for retries). This provides complete visibility into:
    - Which server processed which planet
    - How long each job took
    - Success/failure status and error details
    
    Attributes:
        planet: The planet that was processed
        server: The server that did the processing
        start_time: When the job was assigned
        end_time: When the job finished (success or failure)
        status: Outcome of the job
        error_message: Details if failed (includes retry count)
        duration_seconds: Processing time in seconds
    
    Status Values:
        started: Job is currently in progress
        completed: Job finished successfully
        failed: Job encountered an error (may retry)
        timeout: Server went offline mid-job
    
    Retry Behavior:
        When a job fails and retries, the SAME TaskHistory record is reused.
        This prevents database bloat from rapid retry cycles.
        The error_message field shows retry history: "[Retry 3/5] Error details"
    
    Query Optimization:
        Indexed on start_time (descending) for efficient "recent tasks" queries.
        Default ordering is newest first (-start_time).
    """
    
    STATUS_CHOICES = [
        ('started', 'Started'),       # In progress
        ('completed', 'Completed'),   # Success
        ('failed', 'Failed'),         # Error (may retry)
        ('timeout', 'Timeout'),       # Server went offline
    ]

    # --- Relationships ---
    planet = models.ForeignKey(
        Planet, 
        on_delete=models.CASCADE,
        help_text="Planet that was processed"
    )
    server = models.ForeignKey(
        UnityServer, 
        on_delete=models.SET_NULL, 
        null=True,
        help_text="Server that processed the job"
    )
    
    # --- Timing ---
    start_time = models.DateTimeField(
        auto_now_add=True, 
        db_index=True,
        help_text="When job was assigned"
    )
    end_time = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When job finished"
    )
    
    # --- Outcome ---
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='started',
        help_text="Job outcome"
    )
    error_message = models.TextField(
        null=True, 
        blank=True,
        help_text="Error details if failed"
    )
    duration_seconds = models.FloatField(
        null=True, 
        blank=True,
        help_text="Processing time in seconds"
    )

    class Meta:
        verbose_name = "Task History"
        verbose_name_plural = "Task Histories"
        ordering = ['-start_time']  # Newest first
        indexes = [
            models.Index(fields=['-start_time']),
        ]

    def __str__(self) -> str:
        return f"History: Planet {self.planet.planet_id} on {self.server} ({self.status})"
