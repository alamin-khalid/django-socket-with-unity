import os
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
import game_manager.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server_orchestrator.settings")

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": URLRouter(
        game_manager.routing.websocket_urlpatterns
    ),
})
