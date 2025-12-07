from django.db import models

class GameServer(models.Model):
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('busy', 'Busy'),
        ('idle', 'Idle'),
    ]

    server_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline')
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    current_task = models.ForeignKey('MapPlanet', on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_server')
    
    def __str__(self):
        return f"{self.server_id} ({self.status})"

class MapPlanet(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'), # Or 'waiting' for next round
    ]

    map_id = models.IntegerField(primary_key=True)
    next_round_time = models.DateTimeField(null=True, blank=True)
    season_id = models.IntegerField(default=1)
    round_id = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    def __str__(self):
        return f"Map {self.map_id} - Round {self.round_id}"

class TaskHistory(models.Model):
    map = models.ForeignKey(MapPlanet, on_delete=models.CASCADE)
    server = models.ForeignKey(GameServer, on_delete=models.SET_NULL, null=True)
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    
    def __str__(self):
        return f"History: Map {self.map.map_id} on {self.server}"
