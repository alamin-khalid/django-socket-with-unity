"""
Django-Unity Server Orchestrator - Test Data Setup Script

Run this script to create test data for the system:
python manage.py shell < create_test_data.py

Or manually in Django shell:
python manage.py shell
exec(open('create_test_data.py').read())
"""

from game_manager.models import MapPlanet
from game_manager.redis_queue import add_map_to_queue
from datetime import datetime, timedelta
from django.utils import timezone

print("=" * 60)
print("Creating Test Data for Django-Unity Server Orchestrator")
print("=" * 60)

# Clear existing test data (optional - comment out if you want to keep existing data)
# print("\n1. Clearing existing test data...")
# MapPlanet.objects.filter(map_id__startswith='test_map_').delete()
# print("   ✓ Cleared existing test maps")

# Create test maps with staggered schedule times
print("\n1. Creating test maps...")

test_maps = [
    {
        'map_id': 'test_map_alpha',
        'name': 'Alpha Test Arena',
        'season_id': 1,
        'round_id': 0,
        'next_round_time': timezone.now() + timedelta(seconds=15),
        'status': 'queued',
        'map_data': {
            'difficulty': 'easy',
            'size': 100,
            'terrain': 'plains',
            'max_players': 10
        }
    },
    {
        'map_id': 'test_map_beta',
        'name': 'Beta Test Mountains',
        'season_id': 1,
        'round_id': 0,
        'next_round_time': timezone.now() + timedelta(seconds=30),
        'status': 'queued',
        'map_data': {
            'difficulty': 'medium',
            'size': 150,
            'terrain': 'mountains',
            'max_players': 15
        }
    },
    {
        'map_id': 'test_map_gamma',
        'name': 'Gamma Test Desert',
        'season_id': 1,
        'round_id': 0,
        'next_round_time': timezone.now() + timedelta(seconds=45),
        'status': 'queued',
        'map_data': {
            'difficulty': 'hard',
            'size': 200,
            'terrain': 'desert',
            'max_players': 20
        }
    },
]

created_count = 0
for map_config in test_maps:
    map_obj, created = MapPlanet.objects.get_or_create(
        map_id=map_config['map_id'],
        defaults=map_config
    )
    
    if created:
        print(f"   ✓ Created: {map_obj.name} (ID: {map_obj.map_id})")
        print(f"     - Next round: {map_obj.next_round_time}")
        print(f"     - Map data: {map_obj.map_data}")
        created_count += 1
    else:
        print(f"   ⚠ Already exists: {map_obj.name} (ID: {map_obj.map_id})")

print(f"\n2. Adding maps to Redis queue...")

for map_obj in MapPlanet.objects.filter(status='queued'):
    add_map_to_queue(map_obj.map_id, map_obj.next_round_time)
    print(f"   ✓ Queued: {map_obj.map_id} for {map_obj.next_round_time}")

print("\n" + "=" * 60)
print("Test Data Setup Complete!")
print("=" * 60)

print("\nNext steps:")
print("1. Start Redis:     redis-server")
print("2. Start Django:    python manage.py runserver")
print("3. Start Celery Worker:  celery -A server_orchestrator worker --loglevel=info --pool=solo")
print("4. Start Celery Beat:    celery -A server_orchestrator beat --loglevel=info")
print("5. Connect Unity servers with serverId='unity_01', 'unity_02', etc.")
print("\nThe system will automatically assign jobs to connected Unity servers!")
print("=" * 60)
