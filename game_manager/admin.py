"""
Game Manager - Django Admin Configuration
==========================================

Registers models for the Django admin interface, providing
CRUD operations and filtering for UnityServer, Planet, and TaskHistory.

Access: /admin/
"""

from django.contrib import admin
from .models import UnityServer, Planet, TaskHistory

@admin.register(UnityServer)
class UnityServerAdmin(admin.ModelAdmin):
    list_display = ('server_id', 'status', 'last_heartbeat', 'current_task', 'total_completed_planet', 'total_failed_planet')
    list_filter = ('status',)
    search_fields = ('server_id',)
    ordering = ('server_id',)

@admin.register(Planet)
class PlanetAdmin(admin.ModelAdmin):
    list_display = ('planet_id', 'season_id', 'round_id', 'status', 'next_round_time', 'last_processed')
    list_filter = ('status', 'season_id')
    search_fields = ('planet_id',)
    ordering = ('-next_round_time',)

@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    list_display = ('planet', 'server', 'status', 'start_time', 'end_time', 'duration_seconds')
    list_filter = ('status', 'server', 'start_time')
    search_fields = ('planet__planet_id', 'server__server_id')
    ordering = ('-start_time',)
    date_hierarchy = 'start_time'
    actions = ['batch_delete_selected', 'delete_all_task_history']
    list_per_page = 5000

    @admin.action(description="🗑️ Batch delete selected (safe for large sets)")
    def batch_delete_selected(self, request, queryset):
        """Delete selected records in batches of 500 to avoid timeout."""
        total = queryset.count()
        deleted = 0
        batch_size = 500
        ids = list(queryset.values_list('id', flat=True))
        
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            TaskHistory.objects.filter(id__in=batch_ids).delete()
            deleted += len(batch_ids)
        
        self.message_user(request, f"✅ Deleted {deleted} of {total} task history records.")

    @admin.action(description="⚠️ Delete ALL task history records")
    def delete_all_task_history(self, request, queryset):
        """Delete ALL task history records in batches."""
        total = TaskHistory.objects.count()
        deleted = 0
        batch_size = 500
        
        while TaskHistory.objects.exists():
            ids = list(TaskHistory.objects.values_list('id', flat=True)[:batch_size])
            TaskHistory.objects.filter(id__in=ids).delete()
            deleted += len(ids)
        
        self.message_user(request, f"✅ Deleted all {total} task history records.")
