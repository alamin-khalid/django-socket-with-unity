"""
Game Manager - WebSocket Consumers
===================================

This module defines Django Channels WebSocket consumers for real-time communication
with Unity game servers. It's the bridge between the orchestration system and the
actual game computation nodes.

Communication Flow
------------------
    ┌──────────────┐          WebSocket           ┌────────────────┐
    │    Django    │  ◄─────────────────────────► │  Unity Server  │
    │ (Orchestrator)│                              │  (Game Engine) │
    └──────────────┘                              └────────────────┘
    
    Unity → Django:
        - heartbeat: "I'm alive" + resource metrics
        - status_update: "I'm idle/busy"
        - job_done: "Finished planet X, next round at Y"
        - error: "Failed to process planet X"
    
    Django → Unity:
        - assign_job: "Process planet X with these parameters"
        - command: "restart", "stop", etc.
        - pong: Heartbeat acknowledgment

WebSocket URL Pattern
---------------------
    ws://server:8000/ws/server/{server_id}/
    
    Example: ws://localhost:8000/ws/server/unity_192_168_1_100/

Connection Lifecycle
--------------------
    1. Unity connects → register_server() creates/updates UnityServer record
    2. Unity marked as 'idle' → trigger_assignment() looks for pending jobs
    3. During operation: heartbeats every 5-10 seconds
    4. On disconnect → mark_server_offline() + job recovery

Event-Driven Assignment
-----------------------
Unlike pure polling, this consumer triggers job assignment immediately when:
- A new server connects (becomes idle)
- A server finishes a job (becomes idle again)
- A server reports idle status

This provides lower latency than waiting for the next scheduler tick.

Author: Krada Games
Last Modified: 2024-12
"""

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from typing import Dict, Any, Optional
import logging

from .models import UnityServer, Planet, TaskHistory

logger = logging.getLogger(__name__)


class ServerConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer handling bidirectional communication with Unity servers.
    
    Each Unity game server maintains a single persistent WebSocket connection
    to this consumer. The consumer handles all message routing, state management,
    and integration with the job assignment system.
    
    Attributes:
        server_id (str): Unique identifier extracted from WebSocket URL
        room_group_name (str): Channel layer group for targeted messaging
    
    Threading Model:
        - WebSocket I/O is async (non-blocking)
        - Database operations wrapped with @database_sync_to_async
        - Celery tasks dispatched asynchronously with .delay()
    
    Message Protocol:
        All messages are JSON with a 'type' field for routing.
        See receive_json() for complete message type documentation.
    """
    
    # =========================================================================
    # CONNECTION LIFECYCLE
    # =========================================================================
    
    async def connect(self) -> None:
        """
        Handle new WebSocket connection from Unity server.
        
        Flow:
        1. Extract server_id from URL path
        2. Join channel group for targeted messaging
        3. Accept WebSocket connection
        4. Register server in database (creates or updates UnityServer)
        5. Trigger immediate assignment check (may receive job instantly)
        
        URL Format:
            /ws/server/{server_id}/
        """
        # Extract server identifier from URL route
        self.server_id: str = self.scope['url_route']['kwargs']['server_id']
        self.room_group_name: str = f'server_{self.server_id}'
        
        # Join server-specific channel group for targeted messages
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # Accept the WebSocket connection
        await self.accept()
        
        # Create or update server record in database
        await self.register_server()
        
        logger.info(f"[WebSocket] ✅ Server {self.server_id} connected and registered")
        
        # Immediately check for pending work
        # This provides instant job assignment without waiting for scheduler
        await self.trigger_assignment()

    async def disconnect(self, close_code: int) -> None:
        """
        Handle WebSocket disconnection from Unity server.
        
        Performs cleanup:
        1. Mark server as offline in database
        2. Recover any in-progress jobs back to queue
        3. Leave channel group
        
        Args:
            close_code: WebSocket close code (1000 = normal, others = error)
        """
        logger.info(f"[WebSocket] Server {self.server_id} disconnecting (code: {close_code})")
        
        # Mark offline and recover orphaned jobs
        await self.mark_server_offline()
        
        # Leave channel group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        logger.info(f"[WebSocket] ❌ Server {self.server_id} disconnected and cleaned up")

    # =========================================================================
    # MESSAGE ROUTING
    # =========================================================================

    async def receive_json(self, content: Dict[str, Any]) -> None:
        """
        Route incoming JSON messages from Unity to appropriate handlers.
        
        Message Types (Unity → Django):
        
        1. heartbeat - Periodic health check with resource metrics
            {
                "type": "heartbeat",
                "idle_cpu": 15.2,
                "idle_ram": 40.5,
                "max_cpu": 75.0,
                "max_ram": 85.0,
                "disk": 60.0
            }
        
        2. status_update - Server state change notification
            {
                "type": "status_update",
                "status": "idle" | "busy"
            }
        
        3. job_done - Job completion report
            {
                "type": "job_done",
                "planet_id": "79001",
                "next_round_time": "2025-12-12T03:00:00Z",
                "season_id": 42,
                "round_id": 65,
                "round_number": 1234
            }
        
        4. error - Job failure report
            {
                "type": "error",
                "planet_id": "79001",
                "error": "Out of memory during calculation"
            }
        
        5. disconnect - Graceful shutdown notification
            {
                "type": "disconnect"
            }
        
        Args:
            content: Parsed JSON message from Unity
        """
        message_type = content.get('type', 'unknown')
        
        logger.debug(f"[WebSocket] ⬇ Received from {self.server_id}: {message_type}")
        
        # Route to appropriate handler
        if message_type == 'heartbeat':
            await self.handle_heartbeat(content)
            # Respond with pong to confirm connection is alive
            await self.send_json({
                'type': 'pong',
                'server_time': timezone.now().isoformat()
            })
            
        elif message_type == 'status_update':
            await self._handle_status_update_with_assignment(content)
            
        elif message_type == 'job_done':
            self.handle_job_done(content)
            # Server is now idle - check for more work
            await self.trigger_assignment()
            
        elif message_type == 'error':
            self.handle_error(content)
            
        elif message_type == 'disconnect':
            self.handle_disconnect(content)
            
        else:
            logger.warning(f"[WebSocket] Unknown message type: {message_type}")

    # =========================================================================
    # INCOMING MESSAGE HANDLERS
    # =========================================================================

    @database_sync_to_async
    def handle_heartbeat(self, data: Dict[str, Any]) -> None:
        """
        Process heartbeat message and update server metrics.
        
        Unity sends heartbeats every 5-10 seconds with system resource
        information. This data is used for:
        - Health monitoring (detect stale/crashed servers)
        - Dashboard display of server status
        - Future: load-based assignment decisions
        
        Args:
            data: Heartbeat payload with optional resource metrics
        """
        try:
            update_fields = {'last_heartbeat': timezone.now()}
            
            # Update resource metrics if provided
            metric_mapping = {
                'idle_cpu': 'idle_cpu_usage',
                'idle_ram': 'idle_ram_usage',
                'max_cpu': 'max_cpu_usage',
                'max_ram': 'max_ram_usage',
                'disk': 'disk_usage'
            }
            
            for json_key, db_field in metric_mapping.items():
                if json_key in data:
                    update_fields[db_field] = data[json_key]
            
            UnityServer.objects.filter(server_id=self.server_id).update(**update_fields)
            
        except Exception as e:
            logger.error(f"[Heartbeat] Error updating {self.server_id}: {e}")

    @database_sync_to_async
    def handle_status_update(self, data: Dict[str, Any]) -> None:
        """
        Update server operational status in database.
        
        Unity sends status updates when:
        - Starting a job (idle → busy)
        - Finishing a job (busy → idle)
        - Manual state changes
        
        Args:
            data: Status update with 'status' field
        """
        status = data.get('status')
        
        try:
            UnityServer.objects.filter(server_id=self.server_id).update(status=status)
            logger.info(f"[Status] {self.server_id} → {status}")
        except Exception as e:
            logger.error(f"[Status] Error updating {self.server_id}: {e}")

    async def _handle_status_update_with_assignment(self, data: Dict[str, Any]) -> None:
        """
        Handle status update and trigger assignment if server became idle.
        
        This is the event-driven optimization: when a server finishes work
        and becomes idle, immediately check for more work instead of waiting
        for the next scheduler tick.
        
        Args:
            data: Status update payload
        """
        await self.handle_status_update(data)
        
        # If server is now idle, look for work immediately
        if data.get('status') == 'idle':
            await self.trigger_assignment()

    def handle_job_done(self, data: Dict[str, Any]) -> None:
        """
        Process job completion notification from Unity.
        
        Validates required fields and dispatches a Celery task for the
        actual processing (DB updates, requeue, etc.). This keeps the
        WebSocket handler fast and non-blocking.
        
        Args:
            data: Job completion payload with planet_id, next_round_time, etc.
        """
        from .tasks import handle_job_completion
        
        try:
            planet_id = data.get('planet_id')
            next_round_time = data.get('next_round_time')
            
            # Optional fields from Unity (authoritative source)
            season_id = data.get('season_id')
            round_id = data.get('round_id')
            current_round_number = data.get('round_number')
            
            if not planet_id:
                logger.warning("[Job Done] Missing planet_id")
                return
                
            if not next_round_time:
                logger.warning(f"[Job Done] Missing next_round_time for {planet_id}")
                return
            
            # Dispatch to Celery for async processing
            handle_job_completion.delay(
                planet_id=str(planet_id),
                server_id=self.server_id,
                next_round_time_str=next_round_time,
                season_id=int(season_id) if season_id else None,
                round_id=int(round_id) if round_id else None,
                current_round_number=int(current_round_number) if current_round_number else None
            )
            
            logger.info(f"[Job Done] {self.server_id} completed {planet_id}")
            
        except Exception as e:
            logger.error(f"[Job Done] Error processing: {e}")

    def handle_error(self, data: Dict[str, Any]) -> None:
        """
        Process error report from Unity.
        
        Dispatches to Celery task for retry logic handling.
        The error handler will increment retry count and either
        requeue immediately or mark as failed after max retries.
        
        Args:
            data: Error payload with planet_id and error message
        """
        from .tasks import handle_job_error
        
        planet_id = data.get('planet_id')
        error_message = data.get('error', 'Unknown error')
        
        logger.warning(f"[Error] {self.server_id} reported: {error_message}")
        
        if planet_id:
            handle_job_error.delay(str(planet_id), self.server_id, error_message)

    def handle_disconnect(self, data: Dict[str, Any]) -> None:
        """
        Handle graceful disconnect notification from Unity.
        
        Unity sends this before intentionally closing the connection,
        allowing us to distinguish planned shutdowns from crashes.
        
        Args:
            data: Disconnect payload (currently unused)
        """
        logger.info(f"[Disconnect] {self.server_id} is disconnecting gracefully")

    # =========================================================================
    # OUTGOING MESSAGE HANDLERS (Django → Unity)
    # =========================================================================

    async def job_assignment(self, event: Dict[str, Any]) -> None:
        """
        Send job assignment to Unity server.
        
        This handler is invoked by Celery via channel_layer.group_send().
        It transforms the internal event format to the Unity protocol.
        
        Channel Layer Event (from Celery):
            {
                'type': 'job_assignment',
                'planet_id': '79001',
                'season_id': 42,
                'round_id': 65
            }
        
        WebSocket Message (to Unity):
            {
                'type': 'assign_job',
                'planet_id': '79001',
                'season_id': 42,
                'round_id': 65
            }
        
        Args:
            event: Channel layer event from Celery task
        """
        planet_id = event.get('planet_id')
        logger.info(f"[Job Assignment] ⬆ Sending to {self.server_id}: Planet {planet_id}")
        
        await self.send_json({
            'type': 'assign_job',
            'planet_id': planet_id,
            'season_id': event.get('season_id', 1),
            'round_id': event.get('round_id', 0)
        })

    async def send_command(self, event: Dict[str, Any]) -> None:
        """
        Send administrative command to Unity server.
        
        Used for remote management: restart, shutdown, cancel job, etc.
        Commands are typically triggered from the admin dashboard.
        
        Args:
            event: Command event with 'command' and optional 'params'
        """
        command = event.get('command')
        logger.info(f"[Command] ⬆ Sending to {self.server_id}: {command}")
        
        await self.send_json({
            'type': 'command',
            'command': command,
            'params': event.get('params', {})
        })

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    @database_sync_to_async
    def register_server(self) -> None:
        """
        Register Unity server in database when it connects.
        
        Uses update_or_create for idempotency:
        - New server: Creates UnityServer record
        - Reconnecting server: Updates existing record
        
        Server ID Format:
            If server_id follows "unity_XX_XX_XX_XX" pattern,
            the IP address is extracted and stored.
        """
        try:
            # Extract IP from server_id if following naming convention
            server_ip = "unknown"
            if self.server_id.startswith("unity_"):
                ip_parts = self.server_id.replace("unity_", "").split("_")
                if len(ip_parts) == 4:
                    server_ip = ".".join(ip_parts)
            
            UnityServer.objects.update_or_create(
                server_id=self.server_id,
                defaults={
                    'server_ip': server_ip,
                    'status': 'idle',
                    'last_heartbeat': timezone.now(),
                    'idle_cpu_usage': 0.0,
                    'idle_ram_usage': 0.0,
                    'max_cpu_usage': 0.0,
                    'max_ram_usage': 0.0,
                    'disk_usage': 0.0,
                    'connected_at': timezone.now(),
                    'disconnected_at': None
                }
            )
            logger.info(f"[Register] Server registered: {self.server_id} ({server_ip})")
            
        except Exception as e:
            logger.error(f"[Register] Error registering {self.server_id}: {e}")

    async def trigger_assignment(self) -> None:
        """
        Trigger immediate job assignment check.
        
        Called when server becomes available (connect, idle status, job complete).
        Runs the assignment service synchronously in a thread pool to avoid
        blocking the async event loop.
        """
        try:
            from .assignment_service import assign_available_planets
            
            # Run sync function in thread pool
            result = await database_sync_to_async(assign_available_planets)()
            logger.debug(f"[Assignment] ⚡ Result: {result}")
            
        except Exception as e:
            logger.error(f"[Assignment] Error triggering: {e}")

    @database_sync_to_async
    def mark_server_offline(self) -> None:
        """
        Mark server offline and recover any orphaned jobs.
        
        Called on WebSocket disconnect. Uses centralized recovery_service
        to handle job recovery.
        """
        try:
            from .recovery_service import recover_orphaned_job
            
            server = UnityServer.objects.filter(server_id=self.server_id).first()
            
            if not server:
                return
            
            # Use centralized recovery service for orphaned jobs
            planet_id = recover_orphaned_job(server, "WebSocket disconnect")
            if planet_id:
                logger.info(f"[Recovery] ♻ Recovered job {planet_id} from {self.server_id}")
            
            # Mark server as offline
            server.mark_disconnected()
            logger.info(f"[Offline] Server {self.server_id} marked offline")
            
        except Exception as e:
            logger.error(f"[Offline] Error marking {self.server_id} offline: {e}")
