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
        - job_done: {"type": "job_done", "map_id": "...", "next_time": 60}
        - error: {"type": "error", "error": "..."}
        """
        message_type = content.get('type')

        print(f"[WebSocket] ⬇ Received from {self.server_id}: {message_type}")

        if message_type == 'heartbeat':
            await self.handle_heartbeat(content)
        elif message_type == 'status_update':
            await self.handle_status_update(content)

        elif message_type == 'job_done':
            await self.handle_job_done(content)

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
        status = data.get('status')

        try:
            UnityServer.objects.filter(server_id=self.server_id).update(
                status=status
            )
            print(f"[Status] {self.server_id} → {status}")
        except Exception as e:
            print(f"[Status] ❌ Error: {e}")

    @database_sync_to_async
    def handle_job_done(self, data):
        """
        Process job completion from Unity
        Triggers async Celery task to update DB and requeue
        """
        from .tasks import handle_job_completion

        try:
            map_id = data.get('map_id')
            next_time = data.get('next_time', 60)

            # Trigger Celery task
            handle_job_completion.delay(
                map_id=map_id,
                server_id=self.server_id,
                next_time_seconds=next_time
            )

            print(f"[Job Done] ✅ {self.server_id} completed {map_id}")
        except Exception as e:
            print(f"[Job Done] ❌ Error: {e}")

    @database_sync_to_async
    def handle_error(self, data):
        """Process error report from Unity"""
        error_message = data.get('error', 'Unknown error')
        print(f"[Error] ⚠ {self.server_id} reported: {error_message}")

        # TODO: Log to database, notify admins, etc.

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
            'map_id': 'map_001',
            'season_id': 1,
            'round_id': 5
        }

        Unity receives:
        {
            'type': 'assign_job',
            'map_id': 'map_001',
            'season_id': 1,
            'round_id': 5
        }
        """
        print(f"[Job Assignment] ⬆ Sending to {self.server_id}: Map {event.get('map_id')}")

        await self.send_json({
            'type': 'assign_job',
            'map_id': event.get('map_id'),
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
                from .redis_queue import add_map_to_queue
                add_map_to_queue(planet.map_id, planet.next_round_time)

                print(f"[Recovery] ♻ Recovered job {planet.map_id} from {self.server_id}")

                # Mark task history as timeout
                TaskHistory.objects.filter(
                    map=planet,
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
