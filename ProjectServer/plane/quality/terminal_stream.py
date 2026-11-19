"""Low-latency browser transport over the existing terminal authorization boundary."""
import asyncio
import json
from urllib.parse import urlsplit

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from io import BytesIO
from django.core.handlers.wsgi import WSGIRequest
from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings
from django.contrib.auth import get_user
from importlib import import_module
from types import SimpleNamespace
from rest_framework.exceptions import APIException
from django.http import Http404

from .remote_diagnostics import RemoteSession
from .remote_models import RemoteTerminalEvent


@database_sync_to_async
def session_request(user, pk, action=None, after=0, session_key=None):
    if session_key:
        session = import_module(settings.SESSION_ENGINE).SessionStore(session_key=session_key)
        user = get_user(SimpleNamespace(session=session))
    raw = json.dumps(action).encode() if action is not None else b""
    request = WSGIRequest({
        "REQUEST_METHOD": "GET" if action is None else "POST", "PATH_INFO": "/",
        "QUERY_STRING": "after=" + str(after), "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)), "SERVER_NAME": "localhost", "SERVER_PORT": "80",
        "wsgi.url_scheme": "http", "wsgi.input": BytesIO(raw),
    })
    request.user = user
    if not user or not user.is_authenticated or not user.is_active:
        return 403, {"error": "终端登录已失效。"}
    # Reuse terminal-specific owner/device/target checks, without synchronizing
    # unrelated workspace memberships for every streamed frame.
    view = RemoteSession()
    view.args = ()
    view.kwargs = {"pk": pk}
    request = view.initialize_request(request)
    view.request = request
    try:
        response = view.get(request, pk) if action is None else view.post(request, pk)
    except (APIException, Http404) as error:
        return getattr(error, "status_code", 404), {"error": "终端权限或连接已变化，请重新连接。"}
    return response.status_code, response.data


@database_sync_to_async
def has_output(pk, after):
    return RemoteTerminalEvent.objects.filter(session_id=pk, id__gt=after).exists()


class TerminalConsumer(AsyncJsonWebsocketConsumer):
    @classmethod
    async def encode_json(cls, content):
        return json.dumps(content, cls=DjangoJSONEncoder)

    async def connect(self):
        self.output_task = None
        headers = dict(self.scope.get("headers", []))
        origin = urlsplit(headers.get(b"origin", b"").decode())
        host = headers.get(b"host", b"").decode()
        user = self.scope.get("user")
        if (origin.scheme not in {"http", "https"} or origin.netloc != host
                or not user or not user.is_authenticated):
            await self.close(code=4403)
            return
        self.pk = self.scope["url_route"]["kwargs"]["pk"]
        self.user = user
        self.session_key = getattr(self.scope.get("session"), "session_key", None)
        self.cursor = 0
        self.last_seq = 0
        status, snapshot = await session_request(user, self.pk, session_key=self.session_key)
        if status != 200 or snapshot.get("status") != "open":
            await self.close(code=4403)
            return
        await self.accept()
        await self.publish(snapshot)
        self.output_task = asyncio.create_task(self.forward_output())

    async def publish(self, snapshot):
        self.cursor = max(self.cursor, snapshot.get("cursor", 0))
        await self.send_json({"type": "output", **snapshot})
        if snapshot.get("status") != "open":
            await self.close(code=1000)
            return False
        return True

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data is not None or not text_data or len(text_data) > 12000:
            await self.close(code=4400)
            return
        try:
            await super().receive(text_data=text_data, **kwargs)
        except (ValueError, TypeError, KeyError):
            await self.close(code=4400)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get("action") not in {"input", "resize"}:
            await self.close(code=4400)
            return
        seq = content.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq != self.last_seq + 1:
            await self.close(code=4400)
            return
        status, result = await session_request(self.user, self.pk, content, session_key=self.session_key)
        if status != 200:
            await self.send_json({"type": "error", "error": result.get("error", "终端权限或连接已变化，请重新连接。")})
            await self.close(code=4403)
            return
        self.last_seq = seq
        await self.send_json({"type": "ack", "seq": seq})

    async def forward_output(self):
        # Cheap event probes avoid full authorization queries on every timer tick.
        # Recheck ownership, device identity, and revocation at least once per second.
        last_check = asyncio.get_running_loop().time()
        try:
            while True:
                await asyncio.sleep(0.05)
                now = asyncio.get_running_loop().time()
                if now - last_check < 1 and not await has_output(self.pk, self.cursor):
                    continue
                status, snapshot = await session_request(self.user, self.pk, after=self.cursor, session_key=self.session_key)
                last_check = now
                if status != 200:
                    await self.close(code=4403)
                    return
                if not await self.publish(snapshot):
                    return
        except asyncio.CancelledError:
            pass
        except Exception:
            # Do not send credentials, terminal content, or internal errors to clients.
            await self.close(code=1011)

    async def disconnect(self, code):
        if self.output_task:
            self.output_task.cancel()
            await self.output_task
        if self.output_task:
            await session_request(self.user, self.pk, {"action": "close"}, session_key=self.session_key)
        # Rejected upgrades leave the REST fallback session available.
