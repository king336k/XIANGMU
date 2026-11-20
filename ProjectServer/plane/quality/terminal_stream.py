"""Low-latency browser transport over the existing terminal authorization boundary."""
import asyncio
import json
import time
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


# Keep sequence allocation and bounded append atomic across API workers.
# https://redis.io/docs/latest/develop/programmability/eval-intro/
_APPEND_FAST_OUTPUT = """
for _, raw in ipairs(ARGV) do
    local event = cjson.decode(raw)
    event.fast_seq = redis.call('INCR', KEYS[2])
    redis.call('RPUSH', KEYS[1], cjson.encode(event))
end
redis.call('LTRIM', KEYS[1], -8, -1)
redis.call('EXPIRE', KEYS[1], 60)
redis.call('EXPIRE', KEYS[2], 120)
return #ARGV
"""


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


@database_sync_to_async
def fast_output(pk):
    from django_redis import get_redis_connection
    try:
        return sorted([json.loads(row) for row in get_redis_connection('default').lrange('remote:terminal-output:'+str(pk),-8,-1)],key=lambda row:row.get('fast_seq',0))
    except Exception:
        return []


@database_sync_to_async
def publish_fast_output(station_id, outputs):
    from django_redis import get_redis_connection
    from .remote_models import RemoteTerminal
    from .remote_access import permitted
    from .remote_diagnostics import terminal_target_valid
    from django.utils import timezone
    import base64
    if not isinstance(outputs,list)or not outputs or len(outputs)>100:return
    try:client=get_redis_connection('default')
    except Exception:return
    sessions={str(row.id):row for row in RemoteTerminal.objects.filter(workstation_id=station_id,status='open',expires_at__gt=timezone.now()).select_related('owner','workstation__agent__project__workspace')}
    valid={}
    authorized={}
    for event in outputs:
        if not isinstance(event,dict):return
        session=sessions.get(str(event.get('session_id')))
        if not session or event.get('kind')!='data':continue
        # This local decision never survives into another batch or another session.
        if session.id not in authorized:
            authorized[session.id] = (
                permitted(session.owner,session.workstation) and terminal_target_valid(session,session.workstation)
            )
        if not authorized[session.id]:continue
        try:raw=base64.b64decode(event.get('data',''),validate=True)
        except Exception:continue
        source=event.get('id')
        if len(raw)>65536 or not isinstance(source,str)or not 1<=len(source)<=80:continue
        valid.setdefault(str(session.id), []).append(json.dumps({'source_id':source,'data':event['data']}))
    if not valid:
        return
    try:
        with client.pipeline(transaction=False)as pipe:
            for sid, events in valid.items():
                key='remote:terminal-output:'+sid
                pipe.eval(_APPEND_FAST_OUTPUT, 2, key, key+':seq', *events)
            pipe.execute()
    except Exception:pass


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
        self.fast_seen = set()
        self.fast_sequence = 0
        self.fast_disabled = False
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
                immediate=[]
                if not self.fast_disabled:
                    for event in await fast_output(self.pk):
                        if event.get('fast_seq',0)<=self.fast_sequence:continue
                        if event.get('fast_seq')!=self.fast_sequence+1:
                            self.fast_disabled=True;break
                        self.fast_sequence=event['fast_seq']
                        if event['source_id']not in self.fast_seen:immediate.append(event)
                if immediate:
                    status,current=await session_request(self.user,self.pk,after=self.cursor,session_key=self.session_key)
                    if status!=200:
                        await self.close(code=4403);return
                    if current.get('status')!='open':
                        await self.publish(current);return
                    self.fast_seen.update(event['source_id']for event in immediate)
                    if len(self.fast_seen)>512:self.fast_seen={event['source_id']for event in immediate}
                    await self.send_json({'type':'fast_output','events':immediate})
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


@database_sync_to_async
def station_exchange(raw, payload):
    from .remote_diagnostics import RemoteExchange
    data = json.dumps(payload).encode()
    request = WSGIRequest({"REQUEST_METHOD":"POST","PATH_INFO":"/","QUERY_STRING":"",
        "CONTENT_TYPE":"application/json","CONTENT_LENGTH":str(len(data)),
        "HTTP_AUTHORIZATION":"Bearer "+raw,"SERVER_NAME":"localhost","SERVER_PORT":"80",
        "wsgi.url_scheme":"http","wsgi.input":BytesIO(data)})
    response = RemoteExchange.as_view()(request)
    return response.status_code, response.data


@database_sync_to_async
def pending_station_commands(station_id):
    from .remote_models import RemoteCommand
    from django.utils import timezone
    return RemoteCommand.objects.filter(workstation_id=station_id,status="pending",expires_at__gt=timezone.now()).exists()


@database_sync_to_async
def station_identity(raw):
    from .remote_diagnostics import WorkstationAuthentication
    from rest_framework.request import Request
    request = WSGIRequest({"REQUEST_METHOD":"GET","PATH_INFO":"/","QUERY_STRING":"",
        "HTTP_AUTHORIZATION":"Bearer "+raw,"SERVER_NAME":"localhost","SERVER_PORT":"80",
        "wsgi.url_scheme":"http","wsgi.input":BytesIO()})
    try:
        _, station = WorkstationAuthentication().authenticate(Request(request))
        return str(station.id)
    except APIException:
        return None


class StationConsumer(AsyncJsonWebsocketConsumer):
    @classmethod
    async def encode_json(cls, content):
        return json.dumps(content, cls=DjangoJSONEncoder)

    async def connect(self):
        self.task = None
        self.lock = asyncio.Lock()
        self.identity = None
        self.seq = 0
        self.sent_commands = {}
        headers = dict(self.scope.get("headers", []))
        credential = headers.get(b"authorization", b"").decode()
        if headers.get(b"origin") or not credential.startswith("Bearer rw_") or len(credential)>128:
            await self.close(code=4403); return
        self.raw = credential.removeprefix("Bearer ")
        self.station_id = await station_identity(self.raw)
        if self.station_id is None:
            await self.close(code=4403); return
        await self.accept()
        await self.send_json({"type":"ready"})
        self.task = asyncio.create_task(self.push_commands())

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data is not None or not text_data or len(text_data)>1500000:
            await self.close(code=4400, reason="frame_limit"); return
        try: await super().receive(text_data=text_data, **kwargs)
        except (ValueError,TypeError,KeyError): await self.close(code=4400,reason="invalid_json")

    async def receive_json(self, content, **kwargs):
        if (not isinstance(content,dict) or type(content.get("seq")) is not int
                or content.get("seq")!=self.seq+1 or not isinstance(content.get("payload"),dict)):
            await self.close(code=4400,reason="invalid_sequence"); return
        async with self.lock:
            await publish_fast_output(self.station_id,content["payload"].get("outputs",[]))
            status, result = await station_exchange(self.raw,content["payload"])
            if status!=200:
                await self.close(code=4403,reason="exchange_rejected"); return
            self.seq = content["seq"]
            self.identity = content["payload"].get("identity")
            self.sent_commands.update({row["id"]:row["expires_at"] for row in result.get("commands",[])})
            await self.send_json({"type":"exchange","seq":self.seq,**result})

    async def push_commands(self):
        last_check = asyncio.get_running_loop().time()
        try:
            while True:
                await asyncio.sleep(.03)
                now=asyncio.get_running_loop().time()
                self.sent_commands={key:expiry for key,expiry in self.sent_commands.items()if expiry>time.time()}
                if now-last_check>5 and await station_identity(self.raw) is None:
                    await self.close(code=4403); return
                if now-last_check>5:last_check=now
                if self.identity is None or not await pending_station_commands(self.station_id):continue
                async with self.lock:
                    status,result=await station_exchange(self.raw,{"identity":self.identity,"outputs":[],"results":[]})
                    if status!=200:
                        await self.close(code=4403);return
                    fresh=[row for row in result.get("commands",[])if row["id"]not in self.sent_commands]
                    self.sent_commands.update({row["id"]:row["expires_at"]for row in fresh})
                    if fresh:await self.send_json({"type":"commands","commands":fresh})

        except asyncio.CancelledError:pass
        except Exception as error:
            import logging
            logging.getLogger(__name__).warning("station command stream stopped: %s", type(error).__name__)
            await self.close(code=1011)

    async def disconnect(self, code):
        if self.task:
            self.task.cancel(); await self.task
