from django.urls import path
from . import views

urlpatterns = [
    # REST API Endpoints
    path('map/create/', views.create_map, name='create_map'),  # Must come before map/<str:map_id>/
    path('map/remove/<str:map_id>/', views.remove_map, name='remove_map'),
    path('map/<str:map_id>/', views.get_map_data, name='get_map_data'),
    path('result/', views.submit_result, name='submit_result'),
    path('servers/', views.list_servers, name='list_servers'),
    path('server/<str:server_id>/', views.server_detail, name='server_detail'),
    path('queue/', views.queue_status, name='queue_status'),
    path('command/', views.send_server_command, name='send_command'),
    path('force-assign/', views.force_assign, name='force_assign'),
]
