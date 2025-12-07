from django.urls import path
from . import views

urlpatterns = [
    # REST API Endpoints
    path('api/map/<str:map_id>/', views.get_map_data, name='get_map_data'),
    path('api/result/', views.submit_result, name='submit_result'),
    path('api/servers/', views.list_servers, name='list_servers'),
    path('api/server/<str:server_id>/', views.server_detail, name='server_detail'),
    path('api/queue/', views.queue_status, name='queue_status'),
    path('api/command/', views.send_server_command, name='send_command'),
    
    # Dashboard
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
]
