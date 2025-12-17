from game_manager.assignment_service import assign_available_maps
from game_manager.models import Planet, UnityServer
from game_manager.redis_queue import add_map_to_queue, get_queue_size
from django.utils import timezone

print("--- Starting Verification ---")

# 1. Clean up old test data
Planet.objects.filter(map_id__startswith="debug_map_").delete()
UnityServer.objects.filter(server_id__startswith="unity_debug_").delete()

# 2. Create a Map
m = Planet.objects.create(map_id="debug_map_test", season_id=1, next_round_time=timezone.now())
add_map_to_queue(m.map_id, m.next_round_time)
print(f"Map created. Queue size: {get_queue_size()}")

# 3. Create an Idle Server
s = UnityServer.objects.create(server_id="unity_debug_test", status="idle")
print(f"Server created: {s.server_id} ({s.status})")

# 4. Run Assignment
print("Running assignment...")
result = assign_available_maps()
print(f"Result: {result}")

# 5. Verify
m.refresh_from_db()
s.refresh_from_db()
print(f"Map status: {m.status}, Processing Server: {m.processing_server}")
print(f"Server status: {s.status}, Current Task: {s.current_task}")

if m.status == 'processing' and s.status == 'busy':
    print("✅ SUCCESS: Logic works!")
else:
    print("❌ FAILURE: Logic failed.")
