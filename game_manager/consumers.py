import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import GameServer

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
        
        # Register/Update server in DB
        await self.register_server()
        print(f"Server {self.server_id} connected.")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        # Mark server offline
        await self.mark_server_offline()
        print(f"Server {self.server_id} disconnected.")

    # Receive message from WebSocket
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            action = data.get('action')
            payload = data.get('payload', {})

            if msg_type == 'status':
                await self.handle_status_update(payload)
            elif msg_type == 'event':
                await self.handle_event(action, payload)
            elif msg_type == 'event' and action == 'job_done':
                await self.handle_job_done(payload)
                
        except json.JSONDecodeError:
            print("Failed to decode JSON")

    # Receive message from room group (commands from Django)
    async def server_command(self, event):
        command = event['command']
        
        # Send message to WebSocket
        await self.send(text_data=json.dumps(command))

    @database_sync_to_async
    def register_server(self):
        server, created = GameServer.objects.get_or_create(server_id=self.server_id)
        server.status = 'online'
        server.channel_name = self.channel_name
        server.save()

    @database_sync_to_async
    def mark_server_offline(self):
        try:
            server = GameServer.objects.get(server_id=self.server_id)
            server.status = 'offline'
            server.channel_name = None
            server.save()
        except GameServer.DoesNotExist:
            pass

    @database_sync_to_async
    def handle_status_update(self, payload):
        try:
            server = GameServer.objects.get(server_id=self.server_id)
            server.last_heartbeat = timezone.now()
            
            if 'players' in payload:
                server.current_players = payload['players']
            if 'cpu' in payload:
                # Could log CPU usage or store in a separate metric model
                pass
            
            server.save()
        except GameServer.DoesNotExist:
            pass

    async def handle_event(self, action, payload):
        print(f"Event received from {self.server_id}: {action} - {payload}")
        # Here you could trigger other logic, e.g., match finished

    async def handle_job_done(self, payload):
        print(f"Job Done Event from {self.server_id}: {payload}")
        # Real logic is handled via REST API, this is just for real-time monitoring
        pass
            
    @database_sync_to_async
    def mark_server_idle(self):
        try:
            server = GameServer.objects.get(server_id=self.server_id)
            server.status = 'online' # Back to online/idle
            server.current_task = None
            server.save()
        except GameServer.DoesNotExist:
            pass
