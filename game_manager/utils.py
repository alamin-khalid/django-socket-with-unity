"""
Game Manager - Utility Functions
=================================

Helper functions for sending commands to Unity servers via WebSocket.

Functions
---------
- send_command_to_server(): Send command to specific Unity server
"""

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_command_to_server(server_id: str, action: str, payload: dict = None) -> bool:
    """
    Send a command to a specific Unity server via WebSocket channel layer.
    
    Args:
        server_id: Target server identifier (e.g., 'unity_192_168_1_100')
        action: Command action type (e.g., 'restart_server', 'stop_game')
        payload: Optional additional data for the command
    
    Returns:
        bool: True if command was sent successfully
    
    Example:
        >>> send_command_to_server('unity_001', 'restart_server')
        >>> send_command_to_server('unity_001', 'custom_action', {'key': 'value'})
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
            "type": "send_command",  # Must match consumer method name
            "command": command_data
        }
    )
    return True
