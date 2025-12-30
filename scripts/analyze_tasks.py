"""Analyze TaskHistory to understand why many objects were created."""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server_orchestrator.settings')
django.setup()

from game_manager.models import TaskHistory
from django.db.models import Count
from datetime import timedelta

print("=" * 60)
print("TASK HISTORY ANALYSIS")
print("=" * 60)

total = TaskHistory.objects.count()
print(f"\nTotal records: {total}")

print("\n--- BY STATUS ---")
for s in TaskHistory.objects.values('status').annotate(c=Count('id')).order_by('-c'):
    pct = (s['c'] / total * 100) if total > 0 else 0
    print(f"  {s['status']:12} : {s['c']:5} ({pct:.1f}%)")

print("\n--- FAILED TASKS BY PLANET (Top 10) ---")
for p in TaskHistory.objects.filter(status='failed').values('planet_id').annotate(c=Count('id')).order_by('-c')[:10]:
    print(f"  Planet {p['planet_id']}: {p['c']} failures")

print("\n--- RECENT 30 TASKS (Time Analysis) ---")
print(f"{'Start Time':25} | {'Planet':8} | {'Status':10} | Error")
print("-" * 80)
prev_time = None
for t in TaskHistory.objects.select_related('planet').order_by('-start_time')[:30]:
    error = (t.error_message[:40] + "...") if t.error_message and len(t.error_message) > 40 else (t.error_message or "-")
    
    # Calculate time gap from previous
    gap = ""
    if prev_time:
        diff = prev_time - t.start_time
        if diff < timedelta(seconds=60):
            gap = f" (gap: {diff.seconds}s)"
    
    print(f"{str(t.start_time)[:25]} | {t.planet.planet_id:8} | {t.status:10} | {error}{gap}")
    prev_time = t.start_time

print("\n--- RAPID FIRE ANALYSIS (same planet, <60s apart) ---")
tasks = list(TaskHistory.objects.filter(status='failed').select_related('planet').order_by('planet_id', '-start_time'))
rapid_fire_count = 0
for i in range(len(tasks) - 1):
    if tasks[i].planet_id == tasks[i+1].planet_id:
        diff = tasks[i].start_time - tasks[i+1].start_time
        if diff < timedelta(seconds=60):
            rapid_fire_count += 1
            if rapid_fire_count <= 10:  # Show first 10
                print(f"  {tasks[i].planet_id}: {tasks[i+1].start_time} -> {tasks[i].start_time} ({diff.seconds}s gap)")

print(f"\nTotal rapid-fire failures (<60s between same planet): {rapid_fire_count}")
