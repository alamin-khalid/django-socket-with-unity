from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from .models import MapPlanet, TaskHistory, GameServer
from .serializers import MapPlanetSerializer, TaskResultSerializer
from .queue_manager import add_to_queue

class MapDataView(APIView):
    def get(self, request, map_id):
        try:
            map_planet = MapPlanet.objects.get(map_id=map_id)
            serializer = MapPlanetSerializer(map_planet)
            return Response(serializer.data)
        except MapPlanet.DoesNotExist:
            return Response({"error": "Map not found"}, status=status.HTTP_404_NOT_FOUND)

class TaskResultView(APIView):
    def post(self, request):
        serializer = TaskResultSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            map_id = data['mapId']
            next_time = data['nextTime']
            
            try:
                map_planet = MapPlanet.objects.get(map_id=map_id)
                map_planet.season_id = data['seasonId']
                map_planet.round_id = data['roundId']
                map_planet.next_round_time = next_time
                map_planet.status = 'pending' # Ready for next schedule
                map_planet.save()
                
                # Add to Queue
                add_to_queue(map_id, next_time.timestamp())
                
                # Update History (find open history for this map)
                # In a real app, you'd pass a taskId to link explicitly
                history = TaskHistory.objects.filter(map=map_planet, end_time__isnull=True).last()
                if history:
                    history.end_time = timezone.now()
                    history.result = request.data
                    history.save()
                    
                    # Mark server idle if linked
                    if history.server:
                        history.server.status = 'online' # Idle
                        history.server.current_task = None
                        history.server.save()

                return Response({"status": "success", "next_schedule": next_time})
            except MapPlanet.DoesNotExist:
                return Response({"error": "Map not found"}, status=status.HTTP_404_NOT_FOUND)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

from django.shortcuts import render
from django.views import View
from .utils import send_command_to_server

class DashboardView(View):
    def get(self, request):
        servers = GameServer.objects.all().order_by('server_id')
        # Filter maps that are relevant (processing, pending, or recently done)
        maps = MapPlanet.objects.exclude(status='done').order_by('next_round_time')
        return render(request, 'game_manager/dashboard.html', {'servers': servers, 'maps': maps})

class CommandView(APIView):
    def post(self, request):
        server_id = request.data.get('serverId')
        action = request.data.get('action')
        
        if not server_id or not action:
            return Response({"error": "Missing serverId or action"}, status=status.HTTP_400_BAD_REQUEST)
            
        if send_command_to_server(server_id, action):
            return Response({"status": "success"})
        else:
            return Response({"error": "Failed to send command"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
