from rest_framework import serializers
from .models import MapPlanet, TaskHistory, GameServer

class MapPlanetSerializer(serializers.ModelSerializer):
    processing_server_id = serializers.CharField(source='processing_server.server_id', read_only=True, allow_null=True)
    
    class Meta:
        model = MapPlanet
        fields = [
            'map_id', 
            'name',
            'season_id', 
            'round_id', 
            'next_round_time',
            'status',
            'map_data',
            'last_processed',
            'processing_server_id',
        ]

class GameServerSerializer(serializers.ModelSerializer):
    current_task_id = serializers.CharField(source='current_task.map_id', read_only=True, allow_null=True)
    uptime_seconds = serializers.SerializerMethodField()
    
    class Meta:
        model = GameServer
        fields = [
            'id',
            'server_id',
            'name',
            'status',
            'last_heartbeat',
            'cpu_usage',
            'player_count',
            'current_task_id',
            'connected_at',
            'total_jobs_completed',
            'uptime_seconds',
        ]
    
    def get_uptime_seconds(self, obj):
        if obj.connected_at and obj.status != 'offline':
            from django.utils import timezone
            delta = timezone.now() - obj.connected_at
            return int(delta.total_seconds())
        return 0

class TaskHistorySerializer(serializers.ModelSerializer):
    map_id = serializers.CharField(source='map.map_id', read_only=True)
    server_id = serializers.CharField(source='server.server_id', read_only=True, allow_null=True)
    
    class Meta:
        model = TaskHistory
        fields = [
            'id',
            'map_id',
            'server_id',
            'start_time',
            'end_time',
            'status',
            'result_data',
            'error_message',
            'duration_seconds',
        ]
