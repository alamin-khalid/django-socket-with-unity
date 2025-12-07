import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import GameServer, MapPlanet, TaskHistory
from .redis_queue import add_map_to_queue

class UnityServerConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.server_id = self.scope['url_route']['kwargs']['server_id']
        self.room_group_name = f'server_{self.server_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()
        
        # Register/Update server in DB as idle
        await self.register_server()
        print(f"[WebSocket] Server {self.server_id} connected and registered as idle")

    async def disconnect(self, close_code):
        # Enhanced cleanup with job recovery
        await self.handle_disconnect_cleanup()
        
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        print(f"[WebSocket] Server {self.server_id} disconnected (code: {close_code})")

    # Receive message from WebSocket (from Unity)
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            
            if msg_type == 'heartbeat':
                await self.handle_heartbeat(data)
            elif msg_type == 'status_update':
                await self.handle_status_update(data)
            elif msg_type == 'job_done':
                await self.handle_job_done(data)
            elif msg_type == 'error':
                await self.handle_error(data)
            else:
                print(f"[WebSocket] Unknown message type: {msg_type}")
                
        except json.JSONDecodeError:
            print("[WebSocket] Failed to decode JSON")
        except Exception as e:
            print(f"[WebSocket] Error handling message: {e}")

    # Handler for job assignment (called by Celery via channel layer)
    async def job_assignment(self, event):
        """
        Send job assignment to Unity via WebSocket.
        Called from Celery task via channel_layer.group_send()
        """
        await self.send(text_data=json.dumps({
            'type': 'assign_job',
            'map_id': event['map_id'],
            'map_data': event['map_data'],
            'round_id': event['round_id'],
            'season_id': event['season_id'],
        }))
        print(f"[WebSocket] Sent job assignment to {self.server_id}: map {event['map_id']}")

    @database_sync_to_async
    def register_server(self):
        """Register server as idle when connecting"""
        server, created = GameServer.objects.get_or_create(
            server_id=self.server_id,
            defaults={'name': self.server_id}
        )
        server.status = 'idle'
        server.last_heartbeat = timezone.now()
        server.save()
        
        if created:
            print(f"[DB] Created new server: {self.server_id}")
        else:
            print(f"[DB] Updated existing server: {self.server_id} to idle")

    @database_sync_to_async
    def handle_heartbeat(self, data):
        """
        Update server heartbeat and metrics.
        Unity sends: {type: 'heartbeat', cpu: 45.2, players: 0}
        """
        try:
            server = GameServer.objects.get(server_id=self.server_id)
            server.last_heartbeat = timezone.now()
            
            if 'cpu' in data:
                server.cpu_usage = float(data['cpu'])
            if 'players' in data:
                server.player_count = int(data['players'])
            
            server.save(update_fields=['last_heartbeat', 'cpu_usage', 'player_count'])
            # Don't log every heartbeat to avoid spam
        except GameServer.DoesNotExist:
            print(f"[DB] Server {self.server_id} not found for heartbeat update")

    @database_sync_to_async
    def handle_status_update(self, data):
        """
        Update server status.
        Unity sends: {type: 'status_update', status: 'idle' or 'busy'}
        """
        try:
            status = data.get('status')
            if status not in ['idle', 'busy']:
                print(f"[WebSocket] Invalid status: {status}")
                return
                
            server = GameServer.objects.get(server_id=self.server_id)
            server.status = status
            server.save(update_fields=['status'])
            print(f"[DB] Server {self.server_id} status updated to: {status}")
        except GameServer.DoesNotExist:
            print(f"[DB] Server {self.server_id} not found for status update")

    @database_sync_to_async
    def handle_job_done(self, data):
        """
        Handle job completion notification from Unity.
        Unity sends: {
            type: 'job_done',
            map_id: 'map_1',
            result: {...},
            next_time: 3600  # seconds
        }
        """
        from .tasks import handle_job_completion
        
        map_id = data.get('map_id')
        result = data.get('result', {})
        next_time = data.get('next_time', 3600)
        
        print(f"[WebSocket] Job done notification: {map_id} from {self.server_id}, next in {next_time}s")
        
        # Trigger async job completion handling
        handle_job_completion.delay(
            map_id=map_id,
            server_id=self.server_id,
            result_data=result,
            next_time_seconds=next_time
        )

    @database_sync_to_async
    def handle_error(self, data):
        """
        Handle error notification from Unity.
        Unity sends: {type: 'error', map_id: '...', error: '...'}
        """
        from .tasks import handle_job_error
        
        map_id = data.get('map_id')
        error_message = data.get('error', 'Unknown error')
        
        print(f"[WebSocket] Error notification: {map_id} from {self.server_id}: {error_message}")
        
        # Trigger async error handling
        handle_job_error.delay(
            map_id=map_id,
            server_id=self.server_id,
            error_message=error_message
        )

    @database_sync_to_async
    def handle_disconnect_cleanup(self):
        """
        Enhanced cleanup when server disconnects.
        - Mark server offline
        - If had a job, recover it
        """
        try:
            server = GameServer.objects.get(server_id=self.server_id)
            
            # If had a job, recover it
            if server.current_task:
                map_obj = server.current_task
                print(f"[DB] Recovering job {map_obj.map_id} from disconnecting server {self.server_id}")
                
                # Reset map to queued
                map_obj.status = 'queued'
                map_obj.processing_server = None
                map_obj.save()
                
                # Re-add to queue
                add_map_to_queue(map_obj.map_id, map_obj.next_round_time)
                
                # Mark task history as timeout
                TaskHistory.objects.filter(
                    map=map_obj,
                    server=server,
                    status='started'
                ).update(
                    status='timeout',
                    end_time=timezone.now(),
                    error_message='Server disconnected during processing'
                )
            
            # Mark server offline
            server.status = 'offline'
            server.current_task = None
            server.save()
            
            print(f"[DB] Server {self.server_id} marked offline")
            
        except GameServer.DoesNotExist:
            print(f"[DB] Server {self.server_id} not found during disconnect cleanup")
