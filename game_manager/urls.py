from django.urls import path
from . import views

urlpatterns = [
    # REST API Endpoints - Active
    path('planet/create/', views.create_planet, name='create_planet'),
    path('map/create/', views.create_planet, name='create_map'),  # Alias for planet/create/
    path('planet/remove/<str:planet_id>/', views.remove_planet, name='remove_planet'),
    path('planet/remove/<str:planet_id>', views.remove_planet),  # Allow without trailing slash
    
    path('map/remove/<str:planet_id>/', views.remove_planet, name='remove_map'),  # Alias for planet/remove/
    path('map/remove/<str:planet_id>', views.remove_planet),  # Alias without trailing slash
    path('command/', views.send_server_command, name='send_command'),
    path('force-assign/', views.force_assign, name='force_assign'),
    
    # REST API Endpoints - Reserved for later use
    # path('planet/<str:planet_id>/', views.get_planet_data, name='get_planet_data'),
    # path('result/', views.submit_result, name='submit_result'),
    # path('servers/', views.list_servers, name='list_servers'),
    # path('server/<str:server_id>/', views.server_detail, name='server_detail'),
    # path('queue/', views.queue_status, name='queue_status'),
]
