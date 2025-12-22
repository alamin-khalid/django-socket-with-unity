# game_manager/consumers.py

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .models import UnityServer, Planet, TaskHistory
from django.utils import timezone
import json


class ServerConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for Unity server connections.
    Unity connects to: ws://localhost:8000/ws/server/{server_id}/
    """

    async def connect(self):
        """Called when Unity opens WebSocket connection"""
        # Extract server_id from URL
        self.server_id = self.scope['url_route']['kwargs']['server_id']
        self.room_group_name = f'server_{self.server_id}'

        # Add to group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Accept connection
        await self.accept()

        # Register server as idle
        await self.register_server()

        print(f"[WebSocket] ✅ Server {self.server_id} connected and registered as idle")

        # Trigger immediate assignment check
        await self.trigger_assignment()

    async def disconnect(self, close_code):
        """Called when Unity closes connection"""
        print(f"[WebSocket] Server {self.server_id} disconnecting (code: {close_code})")

        # Mark server offline and recover jobs
        await self.mark_server_offline()

        # Remove from group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        print(f"[WebSocket] ❌ Server {self.server_id} disconnected and marked offline")

    async def receive_json(self, content):
        """
        Route incoming messages from Unity

        Message types:
        - heartbeat: {"type": "heartbeat", "idle_cpu": 15.2, "idle_ram": 40.5, "max_cpu": 75.0, "max_ram": 85.0, "disk": 60.0}
        - status_update: {"type": "status_update", "status": "busy"}
        - job_done: {"type": "job_done", "planet_id": "...", "next_round_time": "2025-12-12T03:00:00Z"}
        - error: {"type": "error", "error": "..."}
        """
        message_type = content.get('type')

        print(f"[WebSocket] ⬇ Received from {self.server_id}: {message_type}")

        if message_type == 'heartbeat':
            await self.handle_heartbeat(content)
            # Send pong response to confirm 2-way communication
            await self.send_json({
                'type': 'pong',
                'server_time': timezone.now().isoformat()
            })

        elif message_type == 'status_update':
            await self.handle_status_update_wrapper(content)  # Use wrapper to trigger assignment on idle

        elif message_type == 'job_done':
            await self.handle_job_done(content)
            await self.trigger_assignment()  # Trigger assignment after job completion

        elif message_type == 'error':
            await self.handle_error(content)

        elif message_type == 'disconnect':
            await self.handle_disconnect(content)

        else:
            print(f"[WebSocket] ⚠ Unknown message type: {message_type}")

    # ================================================================
    # MESSAGE HANDLERS
    # ================================================================

    @database_sync_to_async
    def handle_heartbeat(self, data):
        """
        Update server heartbeat and stats
        Unity sends every 5 seconds with resource metrics
        """
        try:
            update_fields = {
                'last_heartbeat': timezone.now(),
            }

            # Update resource metrics if provided
            if 'idle_cpu' in data:
                update_fields['idle_cpu_usage'] = data['idle_cpu']
            if 'idle_ram' in data:
                update_fields['idle_ram_usage'] = data['idle_ram']
            if 'max_cpu' in data:
                update_fields['max_cpu_usage'] = data['max_cpu']
            if 'max_ram' in data:
                update_fields['max_ram_usage'] = data['max_ram']
            if 'disk' in data:
                update_fields['disk_usage'] = data['disk']

            UnityServer.objects.filter(server_id=self.server_id).update(**update_fields)

        except Exception as e:
            print(f"[Heartbeat] ❌ Error: {e}")

    @database_sync_to_async
    def handle_status_update(self, data):
        """
        Update server status (idle/busy)
        Unity sends when starting/finishing jobs
        """
        import logging
        logger = logging.getLogger(__name__)
        status = data.get('status')

        try:
            UnityServer.objects.filter(server_id=self.server_id).update(
                status=status
            )
            logger.info(f"[Status] {self.server_id} → {status}")
        except Exception as e:
            logger.error(f"[Status] Error: {e}")

    async def handle_status_update_wrapper(self, data):
        """
        Wrapper to handle status update and trigger assignment asynchronously.
        """
        await self.handle_status_update(data)

        # Trigger assignment if server became idle
        if data.get('status') == 'idle':
            await self.trigger_assignment()

    @database_sync_to_async
    def handle_job_done(self, data):
        """
        Process job completion from Unity
        Triggers async Celery task to update DB and requeue
        """
        import logging
        logger = logging.getLogger(__name__)
        from .tasks import handle_job_completion

        try:
            planet_id = data.get('planet_id')
            next_round_time = data.get('next_round_time')

            if not planet_id:
                logger.warning(f"[Job Done] Missing planet_id")
                return
                
            if not next_round_time:
                logger.warning(f"[Job Done] Missing next_round_time for {planet_id}")
                return

            # Trigger Celery task
            handle_job_completion.delay(
                planet_id=str(planet_id),
                server_id=self.server_id,
                next_round_time_str=next_round_time
            )

            logger.info(f"[Job Done] {self.server_id} completed {planet_id}, next: {next_round_time}")
        except Exception as e:
            logger.error(f"[Job Done] Error: {e}")

    @database_sync_to_async
    def handle_error(self, data):
        """Process error report from Unity"""
        from .tasks import handle_job_error
        
        planet_id = data.get('planet_id')
        error_message = data.get('error', 'Unknown error')
        
        print(f"[Error] ⚠ {self.server_id} reported: {error_message}")
        
        if planet_id:
            handle_job_error.delay(str(planet_id), self.server_id, error_message)

    @database_sync_to_async
    def handle_disconnect(self, data):
        """Handle explicit disconnect message from Unity"""
        print(f"[Disconnect] {self.server_id} is disconnecting gracefully")

    # ================================================================
    # MESSAGE SENDING (Django → Unity)
    # ================================================================

    async def job_assignment(self, event):
        """
        Send job assignment to Unity
        Called by Celery via channel_layer.group_send()

        Celery sends:
        {
            'type': 'job_assignment',
            'planet_id': 'planet_001',
            'season_id': 1,
            'round_id': 5
        }

        Unity receives:
        {
            'type': 'assign_job',
            'planet_id': 'planet_001',
            'season_id': 1,
            'round_id': 5
        }
        """
        print(f"[Job Assignment] ⬆ Sending to {self.server_id}: Planet {event.get('planet_id')}")

        await self.send_json({
            'type': 'assign_job',
            'planet_id': event.get('planet_id'),
            'season_id': event.get('season_id', 1),
            'round_id': event.get('round_id', 0)
        })

    async def send_command(self, event):
        """
        Send administrative command to Unity

        Commands: restart_server, stop_server, etc.
        """
        command = event.get('command')
        print(f"[Command] ⬆ Sending to {self.server_id}: {command}")

        await self.send_json({
            'type': 'command',
            'command': command,
            'params': event.get('params', {})
        })

    # ================================================================
    # DATABASE OPERATIONS
    # ================================================================

    @database_sync_to_async
    def register_server(self):
        """
        Register Unity server when it connects
        Creates or updates UnityServer record
        """
        try:
            # Extract IP from server_id if format is unity_XX_XX_XX_XX
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
            print(f"[Register] Server registered: {self.server_id} ({server_ip})")
        except Exception as e:
            print(f"[Register] ❌ Error: {e}")

    async def trigger_assignment(self):
        """
        Trigger assignment check
        """
        try:
            from .assignment_service import assign_available_planets
            # Run synchronous assignment logic in thread
            result = await database_sync_to_async(assign_available_planets)()
            print(f"[Assignment] ⚡ Result: {result}")  # Always log for debugging
        except Exception as e:
            print(f"[Assignment] ❌ Error triggering assignment: {e}")

    @database_sync_to_async
    def mark_server_offline(self):
        """
        Mark server offline when it disconnects
        Recover any jobs that were being processed
        """
        try:
            server = UnityServer.objects.filter(server_id=self.server_id).first()

            if not server:
                return

            # If server had a job, recover it
            if server.current_task:
                planet = server.current_task

                # Mark planet as queued again
                planet.status = 'queued'
                planet.processing_server = None
                planet.save()

                # Re-add to Redis queue
                from .redis_queue import add_planet_to_queue
                add_planet_to_queue(planet.planet_id, planet.next_round_time)

                print(f"[Recovery] ♻ Recovered job {planet.planet_id} from {self.server_id}")

                # Mark task history as timeout
                TaskHistory.objects.filter(
                    planet=planet,
                    server=server,
                    status='started'
                ).update(
                    status='timeout',
                    end_time=timezone.now()
                )

            # Mark server offline
            server.mark_disconnected()

            print(f"[Offline] Server {self.server_id} marked as offline")

        except Exception as e:
            print(f"[Offline] ❌ Error: {e}")
