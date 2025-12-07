from rest_framework import serializers
from .models import MapPlanet, TaskHistory

class MapPlanetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MapPlanet
        fields = ['map_id', 'next_round_time', 'season_id', 'round_id', 'status']

class TaskResultSerializer(serializers.Serializer):
    mapId = serializers.IntegerField()
    seasonId = serializers.IntegerField()
    roundId = serializers.IntegerField()
    nextTime = serializers.DateTimeField()
    # Add other result fields if needed
