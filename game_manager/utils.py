from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def send_command_to_server(server_id, action, payload=None):
    """
    Sends a command to a specific Unity server via WebSockets.
    """
    if payload is None:
        payload = {}
        
    channel_layer = get_channel_layer()
    group_name = f'server_{server_id}'
    
    command_data = {
        "type": "command",
        "action": action,
        "serverId": server_id,
        "payload": payload
    }

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "server_command",
            "command": command_data
        }
    )
    return True
