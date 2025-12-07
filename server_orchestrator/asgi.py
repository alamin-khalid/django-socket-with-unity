import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import game_manager.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server_orchestrator.settings')

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            game_manager.routing.websocket_urlpatterns
        )
    ),
})
