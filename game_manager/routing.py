from django.urls import re_path
from .consumers import ServerConsumer

websocket_urlpatterns = [
    re_path(r"ws/server/(?P<server_id>[^/]+)/$", ServerConsumer.as_asgi()),
]
