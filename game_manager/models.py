from django.db import models
from django.utils import timezone


class UnityServer(models.Model):
    STATUS_CHOICES = [
        ('offline', 'Offline'),
        ('idle', 'Idle'),
        ('busy', 'Busy'),
        ('not_responding', 'Not Responding'),
    ]

    server_id = models.CharField(max_length=100, unique=True, db_index=True)
    server_ip = models.CharField(max_length=100, unique=True, db_index=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', db_index=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True, db_index=True)

    cpu_usage = models.FloatField(default=0.0)
    ram_usage = models.FloatField(default=0.0)

    current_task = models.ForeignKey('Planet', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_server')

    connected_at = models.DateTimeField(auto_now_add=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)

    total_assigned_map = models.IntegerField(default=0)
    total_completed_map = models.IntegerField(default=0)
    total_failed_map = models.IntegerField(default=0)

    def mark_disconnected(self):
        self.disconnected_at = timezone.now()
        self.status = 'offline'
        self.save()

    def __str__(self):
        return f"{self.server_ip} ({self.status})"


class Planet(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('error', 'Error'),
    ]

    map_id = models.CharField(max_length=100, primary_key=True, db_index=True)
    season_id = models.IntegerField(default=1, db_index=True)
    round_id = models.IntegerField(default=0)
    current_round_number = models.IntegerField(default=0)
    next_round_time = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    last_processed = models.DateTimeField(null=True, blank=True)
    processing_server = models.ForeignKey(UnityServer, on_delete=models.SET_NULL, null=True, blank=True, related_name='processing_maps')

    class Meta:
        indexes = [
            models.Index(fields=['next_round_time', 'status']),
        ]

    def __str__(self):
        return f"Map {self.map_id} - Season {self.season_id} - Round {self.round_id}"


class TaskHistory(models.Model):
    STATUS_CHOICES = [
        ('started', 'Started'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('timeout', 'Timeout'),
    ]

    map = models.ForeignKey(Planet, on_delete=models.CASCADE)
    server = models.ForeignKey(UnityServer, on_delete=models.SET_NULL, null=True)
    start_time = models.DateTimeField(auto_now_add=True, db_index=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='started')
    error_message = models.TextField(null=True, blank=True)
    result_data = models.JSONField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['-start_time']),
        ]
        ordering = ['-start_time']

    def __str__(self):
        return f"History: Map {self.map.map_id} on {self.server} ({self.status})"
