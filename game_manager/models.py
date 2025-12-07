from django.db import models

class GameServer(models.Model):
    STATUS_CHOICES = [
        ('offline', 'Offline'),
        ('idle', 'Idle'),
        ('busy', 'Busy'),
    ]

    server_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', db_index=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True, db_index=True)
    cpu_usage = models.FloatField(default=0.0)
    player_count = models.IntegerField(default=0)
    current_task = models.ForeignKey('MapPlanet', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_server')
    connected_at = models.DateTimeField(auto_now_add=True)
    total_jobs_completed = models.IntegerField(default=0)
    
    def __str__(self):
        return f"{self.server_id} ({self.status})"

class MapPlanet(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('error', 'Error'),
    ]

    map_id = models.CharField(max_length=100, primary_key=True, db_index=True)
    name = models.CharField(max_length=200)
    season_id = models.IntegerField(default=1, db_index=True)
    round_id = models.IntegerField(default=0)
    next_round_time = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    map_data = models.JSONField(default=dict)
    last_processed = models.DateTimeField(null=True, blank=True)
    processing_server = models.ForeignKey('GameServer', on_delete=models.SET_NULL, null=True, blank=True, related_name='processing_maps')
    
    class Meta:
        indexes = [
            models.Index(fields=['next_round_time', 'status']),
        ]
    
    def __str__(self):
        return f"{self.name} (Map {self.map_id}) - Round {self.round_id}"

class TaskHistory(models.Model):
    STATUS_CHOICES = [
        ('started', 'Started'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('timeout', 'Timeout'),
    ]
    
    map = models.ForeignKey(MapPlanet, on_delete=models.CASCADE)
    server = models.ForeignKey(GameServer, on_delete=models.SET_NULL, null=True)
    start_time = models.DateTimeField(auto_now_add=True, db_index=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='started')
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['-start_time']),
        ]
        ordering = ['-start_time']
    
    def __str__(self):
        return f"History: Map {self.map.map_id} on {self.server} ({self.status})"
