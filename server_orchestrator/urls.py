from django.contrib import admin
from django.urls import path, include
from game_manager.views import DashboardView, TaskHistoryView, SystemLogsView


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('game_manager.urls')),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('task-history/', TaskHistoryView.as_view(), name='task_history'),
    path('system-logs/', SystemLogsView.as_view(), name='system_logs'),
]

