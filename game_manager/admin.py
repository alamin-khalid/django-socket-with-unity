from django.contrib import admin
from .models import UnityServer, Planet, TaskHistory

@admin.register(UnityServer)
class UnityServerAdmin(admin.ModelAdmin):
    list_display = ('server_id', 'status', 'last_heartbeat', 'current_task')
    list_filter = ('status',)
    search_fields = ('server_id',)

@admin.register(Planet)
class PlanetAdmin(admin.ModelAdmin):
    list_display = ('map_id', 'season_id', 'round_id', 'status', 'next_round_time')
    list_filter = ('status', 'season_id')
    search_fields = ('map_id',)

@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    list_display = ('map', 'server', 'start_time', 'end_time')
    list_filter = ('server', 'start_time')
