from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.shortcuts import render
from django.views import View
from .models import Planet, TaskHistory, UnityServer
from .serializers import PlanetSerializer, UnityServerSerializer
from .redis_queue import get_queue_size, peek_next_due_time
from .utils import send_command_to_server

# ============================================================================
# REST API Endpoints
# ============================================================================

@api_view(['GET'])
def get_map_data(request, map_id):
    """
    Unity calls: GET /api/map/<map_id>/
    Returns map configuration for processing.
    """
    try:
        map_planet = Planet.objects.get(map_id=map_id)
        serializer = PlanetSerializer(map_planet)
        return Response(serializer.data)
    except Planet.DoesNotExist:
        return Response({'error': 'Map not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
def submit_result(request):
    """
    Unity calls: POST /api/result/
    Body: {
        'map_id': '...',
        'server_id': '...',
        'next_time': 3600  # seconds
    }
    Triggers async job completion handling.
    """
    from .tasks import handle_job_completion
    
    map_id = request.data.get('map_id')
    server_id = request.data.get('server_id')
    next_time = request.data.get('next_time', 3600)
    
    if not map_id or not server_id:
        return Response(
            {'error': 'Missing map_id or server_id'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Trigger async job completion
    handle_job_completion.delay(
        map_id=map_id,
        server_id=server_id,
        next_time_seconds=next_time
    )
    
    return Response({'status': 'accepted', 'message': 'Result processing initiated'})

@api_view(['GET'])
def list_servers(request):
    """
    GET /api/servers/
    Returns all server statuses with metrics.
    """
    servers = UnityServer.objects.all().order_by('server_id')
    serializer = UnityServerSerializer(servers, many=True)
    return Response(serializer.data)

@api_view(['GET'])
def queue_status(request):
    """
    GET /api/queue/
    Returns queue statistics for monitoring.
    """
    next_due = peek_next_due_time()
    
    return Response({
        'queue_size': get_queue_size(),
        'next_due_time': next_due.isoformat() if next_due else None,
        'idle_servers': UnityServer.objects.filter(status='idle').count(),
        'busy_servers': UnityServer.objects.filter(status='busy').count(),
        'offline_servers': UnityServer.objects.filter(status='offline').count(),
        'queued_maps': Planet.objects.filter(status='queued').count(),
        'processing_maps': Planet.objects.filter(status='processing').count(),
    })

@api_view(['GET'])
def server_detail(request, server_id):
    """
    GET /api/server/<server_id>/
    Returns detailed information about a specific server.
    """
    try:
        server = UnityServer.objects.get(server_id=server_id)
        serializer = UnityServerSerializer(server)
        return Response(serializer.data)
    except UnityServer.DoesNotExist:
        return Response({'error': 'Server not found'}, status=status.HTTP_404_NOT_FOUND)

# ============================================================================
# Dashboard Views
# ============================================================================

class DashboardView(View):
    """
    Admin dashboard showing server status and map queue.
    """
    def get(self, request):
        servers = UnityServer.objects.all().order_by('server_id')
        maps = Planet.objects.exclude(status='completed').order_by('next_round_time')[:20]
        
        context = {
            'servers': servers,
            'maps': maps,
            'queue_size': get_queue_size(),
            'next_due': peek_next_due_time(),
        }
        
        return render(request, 'game_manager/dashboard.html', context)

# ============================================================================
# Command Views (for manual server control)
# ============================================================================

@api_view(['POST'])
def send_server_command(request):
    """
    POST /api/command/
    Body: {
        'server_id': '...',
        'action': '...',
        'payload': {...}
    }
    Manually send commands to Unity servers.
    """
    server_id = request.data.get('server_id')
    action = request.data.get('action')
    payload = request.data.get('payload', {})

    if not server_id or not action:
        return Response(
            {'error': 'Missing server_id or action'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    if send_command_to_server(server_id, action, payload):
        return Response({'status': 'success', 'message': f'Command sent to {server_id}'})
    else:
        return Response(
            {'error': 'Failed to send command'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
