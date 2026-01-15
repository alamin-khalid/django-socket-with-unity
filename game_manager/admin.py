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
