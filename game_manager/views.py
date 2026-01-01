"""
Game Manager - Views (API & Dashboard)
=======================================

This module provides HTTP endpoints and HTML views for the game server
orchestration system. It serves two main purposes:

1. REST API - Programmatic interface for Unity servers and external systems
2. Dashboard - Human-readable monitoring interface

API Endpoint Summary
--------------------
    GET  /api/planet/<planet_id>/      - Get planet data
    POST /api/planet/create/           - Create new planet
    DELETE /api/planet/remove/<id>/    - Remove planet
    POST /api/result/                  - Submit job result
    GET  /api/servers/                 - List all servers
    GET  /api/server/<server_id>/      - Get server details
    GET  /api/queue/                   - Queue statistics
    POST /api/force-assign/            - Manually trigger assignment
    POST /api/command/                 - Send command to server

Dashboard Views
---------------
    GET  /dashboard/                   - Main monitoring dashboard
    GET  /task-history/                - Full task history view

Authentication Note
-------------------
Currently, these endpoints are unauthenticated. For production:
- Add Django REST Framework authentication (Token, JWT, etc.)
- Protect dashboard with @login_required
- Consider IP whitelisting for Unity servers

Author: Krada Games
Last Modified: 2024-12
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.shortcuts import render
from django.views import View
from typing import Dict, Any
import logging

from .models import Planet, TaskHistory, UnityServer
from .serializers import PlanetSerializer, UnityServerSerializer
from .redis_queue import get_queue_size, peek_next_due_time
from .utils import send_command_to_server

logger = logging.getLogger(__name__)


# =============================================================================
# REST API - PLANET MANAGEMENT
# =============================================================================

@api_view(['GET'])
def get_planet_data(request, planet_id: str) -> Response:
    """
    Retrieve planet data for processing.
    
    Called by Unity servers when they need planet configuration
    to begin a calculation job.
    
    Args:
        planet_id: Unique planet identifier from URL path
    
    Returns:
        200: Serialized planet data
        404: Planet not found
    
    Example Request:
        GET /api/planet/79001/
    
    Example Response:
        {
            "planet_id": "79001",
            "season_id": 42,
            "round_id": 65,
            "current_round_number": 1234,
            "next_round_time": "2025-12-12T03:00:00Z",
            "status": "queued"
        }
    """
    try:
        planet = Planet.objects.get(planet_id=planet_id)
        serializer = PlanetSerializer(planet)
        return Response(serializer.data)
    except Planet.DoesNotExist:
        return Response(
            {'error': 'Planet not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['POST'])
def create_planet(request) -> Response:
    """
    Create a new planet and add it to the processing queue.
    
    This endpoint handles planet registration with validation:
    - Checks for duplicate planet_id
    - Validates format (alphanumeric, underscore, hyphen only)
    - Enforces max length (100 chars)
    - Adds to Redis queue automatically
    - Triggers immediate assignment check
    
    Request Body:
        {
            "planet_id": "planet_123",  // Required (or 'map_id' as alias)
            "season_id": 1              // Required
        }
    
    Returns:
        201: Planet created successfully
        400: Validation error
        409: Duplicate planet_id
    
    Side Effects:
        - Creates Planet record in database
        - Adds planet to Redis scheduling queue
        - Triggers assignment service (may immediately assign to server)
    
    Note:
        next_round_time is automatically set to now, making the planet
        immediately available for processing.
    """
    import re
    from .redis_queue import add_planet_to_queue
    
    # --- Extract planet_id (support legacy 'map_id' alias) ---
    planet_id = request.data.get('planet_id') or request.data.get('map_id')
    
    # --- Validation: Required field ---
    if not planet_id:
        return Response(
            {'error': 'planet_id (or map_id) is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # --- Validation: Format ---
    if not re.match(r'^[a-zA-Z0-9_-]+$', str(planet_id)):
        return Response(
            {'error': 'planet_id must contain only letters, numbers, underscores, and hyphens'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # --- Validation: Length ---
    if len(str(planet_id)) > 100:
        return Response(
            {'error': 'planet_id must be 100 characters or less'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # --- Validation: Uniqueness ---
    if Planet.objects.filter(planet_id=planet_id).exists():
        return Response(
            {'error': f'Planet with planet_id "{planet_id}" already exists'},
            status=status.HTTP_409_CONFLICT
        )
    
    # --- Prepare serializer data ---
    data = request.data.copy()
    
    # Normalize map_id to planet_id
    if 'map_id' in request.data and 'planet_id' not in request.data:
        data['planet_id'] = planet_id
    
    # Set next_round_time to now for immediate processing
    data['next_round_time'] = timezone.now().isoformat()
    
    # --- Create planet ---
    serializer = PlanetSerializer(data=data)
    if serializer.is_valid():
        planet_obj = serializer.save()
        
        # Add to queue and trigger assignment
        try:
            add_planet_to_queue(planet_obj.planet_id, planet_obj.next_round_time)
            
            from .assignment_service import assign_available_planets
            assign_available_planets()
            
        except Exception as e:
            # Log but don't fail - planet is created, queue is secondary
            logger.error(f"Failed to queue/assign planet {planet_obj.planet_id}: {e}")
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    else:
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
def remove_planet(request, planet_id: str) -> Response:
    """
    Remove a planet from the system.
    
    Permanently deletes a planet and its associated data. The pre_delete
    signal automatically removes it from the Redis queue.
    
    Args:
        planet_id: Planet to remove
    
    Returns:
        200: Planet removed successfully
        404: Planet not found
        409: Cannot remove while processing
    
    Protection:
        Planets currently being processed cannot be deleted to prevent
        data inconsistency. Wait for the job to complete or error out.
    
    Cascade Behavior:
        - TaskHistory records are CASCADE deleted with the planet
        - Redis queue entry is removed via pre_delete signal
    """
    try:
        planet = Planet.objects.get(planet_id=planet_id)
        
        # Protect in-progress jobs
        if planet.status == 'processing':
            return Response(
                {'error': f'Cannot remove planet "{planet_id}" while it is being processed'},
                status=status.HTTP_409_CONFLICT
            )
        
        # Delete (triggers pre_delete signal for Redis cleanup)
        planet.delete()
        
        return Response({
            'status': 'success',
            'message': f'Planet "{planet_id}" has been removed'
        })
        
    except Planet.DoesNotExist:
        return Response(
            {'error': f'Planet "{planet_id}" not found'},
            status=status.HTTP_404_NOT_FOUND
        )


# =============================================================================
# REST API - JOB RESULTS
# =============================================================================

@api_view(['POST'])
def submit_result(request) -> Response:
    """
    Submit job completion result (alternative to WebSocket).
    
    This provides an HTTP fallback for Unity servers that prefer REST
    over WebSocket for result submission. The preferred method is
    WebSocket 'job_done' message for lower latency.
    
    Request Body:
        {
            "planet_id": "79001",
            "server_id": "unity_192_168_1_100",
            "next_round_time": "2025-12-12T03:00:00Z"  // ISO 8601
        }
    
    Returns:
        200: Result accepted for processing
        400: Missing required fields or invalid datetime
    
    Processing:
        Dispatches to Celery task for async handling.
        Does not block on database operations.
    """
    from .tasks import handle_job_completion
    from dateutil import parser
    
    planet_id = request.data.get('planet_id')
    server_id = request.data.get('server_id')
    next_round_time_str = request.data.get('next_round_time')
    
    # --- Validation ---
    if not planet_id or not server_id:
        return Response(
            {'error': 'Missing planet_id or server_id'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not next_round_time_str:
        return Response(
            {'error': 'Missing next_round_time'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        next_round_time = parser.isoparse(next_round_time_str)
    except (ValueError, TypeError) as e:
        return Response(
            {'error': f'Invalid datetime format: {str(e)}'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # --- Dispatch to Celery ---
    handle_job_completion.delay(
        planet_id=planet_id,
        server_id=server_id,
        next_round_time_str=next_round_time.isoformat()
    )
    
    return Response({
        'status': 'accepted',
        'message': 'Result processing initiated'
    })


# =============================================================================
# REST API - SERVER MANAGEMENT
# =============================================================================

@api_view(['GET'])
def list_servers(request) -> Response:
    """
    List all registered Unity servers with their current status.
    
    Returns:
        200: Array of server objects with metrics
    
    Example Response:
        [
            {
                "server_id": "unity_192_168_1_100",
                "server_ip": "192.168.1.100",
                "status": "idle",
                "last_heartbeat": "2025-12-22T10:30:00Z",
                "idle_cpu_usage": 15.2,
                "idle_ram_usage": 40.5,
                ...
            }
        ]
    """
    servers = UnityServer.objects.all().order_by('server_id')
    serializer = UnityServerSerializer(servers, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def queue_status(request) -> Response:
    """
    Get current queue and server statistics.
    
    Provides a snapshot of system state for monitoring dashboards
    and health checks.
    
    Returns:
        200: Statistics object
    
    Example Response:
        {
            "queue_size": 15,
            "next_due_time": "2025-12-22T10:35:00Z",
            "idle_servers": 3,
            "busy_servers": 2,
            "offline_servers": 1,
            "queued_planets": 15,
            "processing_planets": 2
        }
    """
    next_due = peek_next_due_time()
    
    return Response({
        'queue_size': get_queue_size(),
        'next_due_time': next_due.isoformat() if next_due else None,
        'idle_servers': UnityServer.objects.filter(status='idle').count(),
        'busy_servers': UnityServer.objects.filter(status='busy').count(),
        'offline_servers': UnityServer.objects.filter(status='offline').count(),
        'queued_planets': Planet.objects.filter(status='queued').count(),
        'processing_planets': Planet.objects.filter(status='processing').count(),
    })


@api_view(['GET'])
def server_detail(request, server_id: str) -> Response:
    """
    Get detailed information about a specific server.
    
    Args:
        server_id: Server identifier from URL path
    
    Returns:
        200: Server details
        404: Server not found
    """
    try:
        server = UnityServer.objects.get(server_id=server_id)
        serializer = UnityServerSerializer(server)
        return Response(serializer.data)
    except UnityServer.DoesNotExist:
        return Response(
            {'error': 'Server not found'},
            status=status.HTTP_404_NOT_FOUND
        )


# =============================================================================
# DASHBOARD VIEWS (HTML)
# =============================================================================

class DashboardView(View):
    """
    Main monitoring dashboard with real-time server and job status.
    
    Provides a comprehensive view of:
    - All registered Unity servers with status and metrics
    - Planet queue with upcoming jobs
    - Recent task history with success/failure rates
    - System-wide statistics
    
    Template: game_manager/dashboard.html
    URL: /dashboard/
    """
    
    def get(self, request) -> render:
        """
        Render dashboard with current system state.
        
        Queries:
        - All servers (ordered by server_id)
        - Active planets (non-completed, next 20)
        - Recent tasks (last 50)
        - Aggregate statistics
        
        Performance Note:
            select_related() is used on TaskHistory to minimize
            database queries when accessing planet and server data.
        """
        from django.db.models import Avg
        
        # --- Fetch Core Data ---
        servers = UnityServer.objects.all().order_by('server_id')
        planets = Planet.objects.exclude(
            status='completed'
        ).order_by('next_round_time')[:20]
        
        # --- Task History with Optimization ---
        recent_tasks = TaskHistory.objects.select_related(
            'planet', 'server'
        ).order_by('-start_time')[:50]
        
        # --- Aggregate Statistics ---
        total_tasks = TaskHistory.objects.count()
        completed_tasks = TaskHistory.objects.filter(status='completed').count()
        failed_tasks = TaskHistory.objects.filter(status='failed').count()
        timeout_tasks = TaskHistory.objects.filter(status='timeout').count()
        
        avg_duration = TaskHistory.objects.filter(
            status='completed',
            duration_seconds__isnull=False
        ).aggregate(Avg('duration_seconds'))['duration_seconds__avg'] or 0
        
        # --- Server Breakdown ---
        idle_servers = servers.filter(status='idle').count()
        busy_servers = servers.filter(status='busy').count()
        offline_servers = servers.filter(status='offline').count()
        not_init_servers = servers.filter(status='not_initialized').count()
        
        # --- Build Context ---
        context = {
            # Core data
            'servers': servers,
            'planets': planets,
            'queue_size': get_queue_size(),
            'next_due': peek_next_due_time(),
            
            # Task history
            'recent_tasks': recent_tasks,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'failed_tasks': failed_tasks,
            'timeout_tasks': timeout_tasks,
            'avg_duration': round(avg_duration, 2),
            'success_rate': round(
                (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
                1
            ),
            
            # Server breakdown
            'idle_servers': idle_servers,
            'busy_servers': busy_servers,
            'offline_servers': offline_servers,
            'not_init_servers': not_init_servers,
            'total_servers': servers.count(),
            
            # Timestamp
            'server_time': timezone.now(),
        }
        
        return render(request, 'game_manager/dashboard.html', context)


class TaskHistoryView(View):
    """
    Full task history view with client-side filtering.
    
    Unlike the dashboard which shows last 50 tasks, this view exports
    ALL task history as JSON for client-side DataTables processing.
    
    Template: game_manager/task_history.html
    URL: /task-history/
    
    Performance Note:
        For very large datasets (100k+ records), consider adding
        server-side pagination with Django REST Framework.
    """
    
    def get(self, request) -> render:
        """
        Render task history with all records as JSON.
        
        The template uses JavaScript DataTables for:
        - Client-side search/filter
        - Pagination
        - Sorting by any column
        
        Note: Server IPs are masked in the backend before sending to client
        for security - the raw IP is never exposed to the browser.
        """
        import json
        from .templatetags.dashboard_filters import mask_server_ip
        
        # Fetch all tasks with related data
        tasks = TaskHistory.objects.select_related(
            'planet', 'server'
        ).order_by('-start_time')
        
        # Convert to JSON-serializable format with masked server IDs
        tasks_data = []
        for task in tasks:
            tasks_data.append({
                'planet_id': task.planet.planet_id if task.planet else 'Unknown',
                'server_id': mask_server_ip(task.server.server_id) if task.server else None,
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


# =============================================================================
# ADMINISTRATIVE ACTIONS
# =============================================================================

@api_view(['POST'])
def force_assign(request) -> Response:
    """
    Manually trigger job assignment.
    
    Bypasses the Celery Beat scheduler and immediately runs the
    assignment service. Useful for debugging or when you've just
    added planets and don't want to wait for the next scheduler tick.
    
    Returns:
        200: Assignment result summary
        500: Internal error
    
    Example Response:
        {
            "status": "success",
            "result": "Assigned 3 planets"
        }
    """
    try:
        from .assignment_service import assign_available_planets
        result = assign_available_planets()
        return Response({
            'status': 'success',
            'result': str(result)
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def send_server_command(request) -> Response:
    """
    Send administrative command to a Unity server.
    
    Allows remote management of Unity servers via WebSocket.
    Commands are forwarded to the specified server's WebSocket connection.
    
    Request Body:
        {
            "server_id": "unity_192_168_1_100",
            "action": "restart",
            "payload": {}  // Optional command-specific data
        }
    
    Returns:
        200: Command sent successfully
        400: Missing required fields
        500: Failed to send (server disconnected?)
    
    Available Actions (Unity implementation dependent):
        - restart: Restart the game server process
        - stop: Gracefully stop the server
        - cancel_job: Cancel current job in progress
        - update_config: Update runtime configuration
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
        return Response({
            'status': 'success',
            'message': f'Command sent to {server_id}'
        })
    else:
        return Response(
            {'error': 'Failed to send command'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
