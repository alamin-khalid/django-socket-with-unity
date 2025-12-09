from rest_framework import serializers
from .models import Planet, TaskHistory, UnityServer

class PlanetSerializer(serializers.ModelSerializer):
    processing_server_id = serializers.CharField(source='processing_server.server_id', read_only=True, allow_null=True)
    
    class Meta:
        model = Planet
        fields = [
            'map_id',
            'season_id', 
            'round_id',
            'current_round_number', 
            'next_round_time',
            'status',
            'last_processed',
            'processing_server_id',
        ]

class UnityServerSerializer(serializers.ModelSerializer):
    current_task_id = serializers.CharField(source='current_task.map_id', read_only=True, allow_null=True)
    uptime_seconds = serializers.SerializerMethodField()
    
    class Meta:
        model = UnityServer
        fields = [
            'id',
            'server_id',
            'status',
            'last_heartbeat',
            'cpu_usage',
            'ram_usage',
            'current_task_id',
            'connected_at',
            'total_completed_map',
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
