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
def create_map(request):
    """
    POST /api/map/create/
    Body: {
        'map_id': 'planet_123',  # Required, also called planetId
        'season_id': 1,           # Required
    }
    Creates a new map/planet with validation to prevent duplicates.
    Automatically adds it the processing queue.
    """
    import re
    from .redis_queue import add_map_to_queue
    
    map_id = request.data.get('map_id')
    
    # Validate that map_id is provided
    if not map_id:
        return Response(
            {'error': 'map_id (planetId) is required'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate map_id format (alphanumeric, underscore, hyphen only)
    if not re.match(r'^[a-zA-Z0-9_-]+$', str(map_id)):
        return Response(
            {'error': 'map_id must contain only letters, numbers, underscores, and hyphens'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate map_id length
    if len(str(map_id)) > 100:
        return Response(
            {'error': 'map_id must be 100 characters or less'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check for duplicate map_id
    if Planet.objects.filter(map_id=map_id).exists():
        return Response(
            {'error': f'Map with map_id "{map_id}" already exists'}, 
            status=status.HTTP_409_CONFLICT
        )
    
    # Prepare data for serializer
    data = request.data.copy()
    
    # Always set next_round_time to NOW
    data['next_round_time'] = timezone.now().isoformat()
    
    # Create the map using serializer
    serializer = PlanetSerializer(data=data)
    if serializer.is_valid():
        map_obj = serializer.save()
        
        # Add to Redis queue for immediate processing
        try:
            add_map_to_queue(map_obj.map_id, map_obj.next_round_time)
            
            # Trigger assignment check immediately
            from .assignment_service import assign_available_maps
            assign_available_maps()
            
        except Exception as e:
            # Log error but don't fail the request
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to add/assign map {map_obj.map_id}: {e}")
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
def remove_map(request, map_id):
    """
    DELETE /api/map/remove/<map_id>/
    Removes a planet/map from the system.
    Will also remove it from the Redis queue (handled by pre_delete signal).
    """
    try:
        map_planet = Planet.objects.get(map_id=map_id)
        
        # Check if the map is currently being processed
        if map_planet.status == 'processing':
            return Response(
                {'error': f'Cannot remove map "{map_id}" while it is being processed'},
                status=status.HTTP_409_CONFLICT
            )
        
        # Delete the planet (pre_delete signal will handle Redis queue cleanup)
        map_planet.delete()
        
        return Response({
            'status': 'success',
            'message': f'Map "{map_id}" has been removed'
        })
        
    except Planet.DoesNotExist:
        return Response(
            {'error': f'Map "{map_id}" not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
def submit_result(request):
    """
    Unity calls: POST /api/result/
    Body: {
        'map_id': '...',
        'server_id': '...',
        'next_round_time': '2025-12-12T03:00:00Z'  # ISO 8601 datetime string
    }
    Triggers async job completion handling.
    """
    from .tasks import handle_job_completion
    
    from dateutil import parser
    
    map_id = request.data.get('map_id')
    server_id = request.data.get('server_id')
    next_round_time_str = request.data.get('next_round_time')
    
    if not map_id or not server_id:
        return Response(
            {'error': 'Missing map_id or server_id'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not next_round_time_str:
        return Response(
            {'error': 'Missing next_round_time'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Parse ISO 8601 datetime string
        next_round_time = parser.isoparse(next_round_time_str)
    except (ValueError, TypeError) as e:
        return Response(
            {'error': f'Invalid datetime format: {str(e)}'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Trigger async job completion
    handle_job_completion.delay(
        map_id=map_id,
        server_id=server_id,
        next_round_time_str=next_round_time.isoformat()
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
        from django.db.models import Avg
        
        servers = UnityServer.objects.all().order_by('server_id')
        maps = Planet.objects.exclude(status='completed').order_by('next_round_time')[:20]
        
        # Get recent task history (last 50 tasks)
        recent_tasks = TaskHistory.objects.select_related(
            'map', 'server'
        ).order_by('-start_time')[:50]
        
        # Calculate statistics
        total_tasks = TaskHistory.objects.count()
        completed_tasks = TaskHistory.objects.filter(status='completed').count()
        failed_tasks = TaskHistory.objects.filter(status='failed').count()
        timeout_tasks = TaskHistory.objects.filter(status='timeout').count()
        
        # Calculate average processing time
        avg_duration = TaskHistory.objects.filter(
            status='completed',
            duration_seconds__isnull=False
        ).aggregate(Avg('duration_seconds'))['duration_seconds__avg'] or 0
        
        # Server statistics
        idle_servers = servers.filter(status='idle').count()
        busy_servers = servers.filter(status='busy').count()
        offline_servers = servers.filter(status='offline').count()
        not_init_servers = servers.filter(status='not_initialized').count()
        
        context = {
            'servers': servers,
            'maps': maps,
            'queue_size': get_queue_size(),
            'next_due': peek_next_due_time(),
            # Task history and statistics
            'recent_tasks': recent_tasks,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'timeout_tasks': timeout_tasks,
            'avg_duration': round(avg_duration, 2),
            'success_rate': round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1),
            # Server statistics
            'idle_servers': idle_servers,
            'busy_servers': busy_servers,
            'offline_servers': offline_servers,
            'not_init_servers': not_init_servers,
            'total_servers': servers.count(),
            # Current server time
            'server_time': timezone.now(),
        }
        
        return render(request, 'game_manager/dashboard.html', context)


class TaskHistoryView(View):
    """
    Full task history page with all records for client-side filtering/pagination.
    """
    def get(self, request):
        import json
        
        # Get all task history
        tasks = TaskHistory.objects.select_related(
            'map', 'server'
        ).order_by('-start_time')
        
        # Convert to JSON-serializable format
        tasks_data = []
        for task in tasks:
            tasks_data.append({
                'map_id': task.map.map_id if task.map else 'Unknown',
                'server_id': task.server.server_id if task.server else None,
                'status': task.status,
                'start_time': task.start_time.isoformat() if task.start_time else None,
                'end_time': task.end_time.isoformat() if task.end_time else None,
                'duration_seconds': task.duration_seconds,
                'error_message': task.error_message,
            })
        
        context = {
            'tasks_json': json.dumps(tasks_data),
            'server_time': timezone.now(),
        }
        
        return render(request, 'game_manager/task_history.html', context)


@api_view(['POST'])
def force_assign(request):
    """
    POST /api/force-assign/
    Manually trigger map assignment to idle servers.
    """
    try:
        from .assignment_service import assign_available_maps
        result = assign_available_maps()
        return Response({
            'status': 'success',
            'result': str(result)
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
