# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.urls import path
from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.


from plane.quality.terminal_stream import TerminalConsumer, StationConsumer

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(URLRouter([
        path("api/quality-auth/remote-diagnostics/terminal-stream/<uuid:pk>/", TerminalConsumer.as_asgi()),
        path("api/quality-auth/remote-diagnostics/station-stream/", StationConsumer.as_asgi()),
    ])),
})
