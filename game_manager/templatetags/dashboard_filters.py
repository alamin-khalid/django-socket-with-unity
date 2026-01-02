"""
Custom template filters and utility functions for the game_manager app.
"""
from django import template
import re

register = template.Library()


def mask_server_ip(server_id):
    """
    Mask IP address in server ID for privacy.
    
    This is a standalone function that can be imported and used in views
    for backend masking, ensuring IPs are never exposed to the client.
    
    Examples:
        unity_103_12_214_244 -> 103.**.***.244
        server_192_168_1_100 -> 192.***.***.100
    
    The function:
    1. Removes any prefix (like "unity_")
    2. Preserves the first and last IP octets
    3. Replaces middle octets with asterisks matching their original length
    4. Returns IP in standard dot notation
    
    Args:
        server_id: The server identifier string (e.g., "unity_103_12_214_244")
        
    Returns:
        str: Masked IP address in dot notation (e.g., "103.**.***.244")
    """
    if not server_id:
        return server_id
    
    # Pattern: prefix_octet1_octet2_octet3_octet4
    # Match server IDs containing IP-like patterns (4 underscore-separated numbers)
    pattern = r'^(.+?)_(\d+)_(\d+)_(\d+)_(\d+)$'
    match = re.match(pattern, str(server_id))
    
    if match:
        octet1 = match.group(2)  # Keep visible (first octet)
        octet2 = match.group(3)  # Mask
        octet3 = match.group(4)  # Mask
        octet4 = match.group(5)  # Keep visible (last octet)
        
        # Replace middle octets with asterisks of same length
        masked_octet2 = '*' * len(octet2)
        masked_octet3 = '*' * len(octet3)
        
        # Return in standard IP dot notation
        return f"{octet1}.{masked_octet2}.{masked_octet3}.{octet4}"
    
    return server_id


# Register as template filter (uses the same function)
@register.filter
def mask_ip(server_id):
    """Template filter wrapper for mask_server_ip function."""
    return mask_server_ip(server_id)
