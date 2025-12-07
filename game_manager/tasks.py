from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import GameServer, MapPlanet, TaskHistory
from .utils import send_command_to_server
from .queue_manager import get_due_tasks, pop_task

@shared_task
def allocate_match_to_server(match_id):
    try:
        match = Match.objects.get(id=match_id)
        if match.status != 'pending':
            return f"Match {match_id} is not pending."

        # Find available server (online and idle)
        # In a real scenario, you might have more complex logic (region, load, etc.)
        server = GameServer.objects.filter(status='online', current_players=0).first()

        if server:
            # Assign server to match
            match.server = server
            match.status = 'running' # Or 'starting'
            match.save()

            # Mark server as busy (optional, depending on logic)
            # server.status = 'busy'
            # server.save()

            # Send command to Unity
            payload = {
                "matchId": match.id,
                "map": "Arena01", # You might store map in Match model
                # "gameMode": match.game_mode 
            }
            send_command_to_server(server.server_id, "start_game", payload)
            
            return f"Match {match_id} allocated to {server.server_id}"
        else:
            return f"No available servers for match {match_id}"

    except Match.DoesNotExist:
        return f"Match {match_id} not found."

@shared_task
def check_server_health():
    # Threshold for considering a server dead (e.g., 30 seconds)
    threshold = timezone.now() - timedelta(seconds=30)
    
    dead_servers = GameServer.objects.filter(status='online', last_heartbeat__lt=threshold)
    
    count = 0
    for server in dead_servers:
        server.status = 'offline'
        server.save()
        count += 1
        print(f"Server {server.server_id} marked offline due to inactivity.")
        
    return f"Checked health. {count} servers marked offline."

from .queue_manager import get_due_tasks, pop_task

@shared_task
def process_map_queue():
    """
    Checks the map queue for due tasks and assigns them to available servers.
    """
    due_maps = get_due_tasks()
    
    if not due_maps:
        return "No maps due for calculation."

    # Find idle servers
    idle_servers = GameServer.objects.filter(status='online', current_task__isnull=True)
    
    assigned_count = 0
    
    for map_id in due_maps:
        if not idle_servers.exists():
            break
            
        server = idle_servers.first()
        
        try:
            map_planet = MapPlanet.objects.get(map_id=map_id)
        except MapPlanet.DoesNotExist:
            pop_task(map_id) # Remove invalid map
            continue

        # Assign task
        payload = {
            "mapId": map_planet.map_id,
            "seasonId": map_planet.season_id,
            "roundId": map_planet.round_id,
            "action": "assign_job"
        }
        
        if send_command_to_server(server.server_id, "assign_job", payload):
            pop_task(map_id)
            
            # Mark server busy and link task
            server.status = 'busy'
            server.current_task = map_planet
            server.save()
            
            map_planet.status = 'processing'
            map_planet.save()
            
            # Create History Entry
            TaskHistory.objects.create(map=map_planet, server=server)
            
            assigned_count += 1
            print(f"Assigned map {map_id} to server {server.server_id}")
        else:
            print(f"Failed to send command to {server.server_id}")

    return f"Processed queue. Assigned {assigned_count} maps."
