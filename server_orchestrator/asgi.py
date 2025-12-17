import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server_orchestrator.settings")

# 🔴 THIS IS MANDATORY
django.setup()

import game_manager.routing  # noqa: E402 (import AFTER setup)

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": URLRouter(
        game_manager.routing.websocket_urlpatterns
    ),
})
