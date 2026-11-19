"""WebSocket terminals reuse the HTTP ownership, revocation, and target checks."""
import asyncio
import json
from importlib import import_module
from types import SimpleNamespace
import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from plane.quality.remote_models import RemoteTerminal
from plane.db.models import User
from uuid import uuid4
from plane.tests.contract.app.test_remote_diagnostics import BASE,heartbeat
pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db(transaction=True)]

@pytest.fixture
def terminal(remote):
    client,edge,device,project=remote;heartbeat(edge)
    opened=client.post(BASE,{'action':'open','device_id':device,'cols':80,'rows':24},format='json')
    assert opened.status_code==201
    row=RemoteTerminal.objects.get(pk=opened.data['id'])
    return row,row.owner

def run_socket(row,user,origin='http://testserver'):
    from plane.quality.terminal_stream import TerminalConsumer
    incoming=asyncio.Queue();outgoing=asyncio.Queue()
    scope={'type':'websocket','path':'/api/quality-auth/remote-diagnostics/terminal-stream/'+str(row.id)+'/',
        'url_route':{'kwargs':{'pk':row.id}},'user':user,'headers':[(b'host',b'testserver'),(b'origin',origin.encode())],
        'query_string':b'','subprotocols':[]}
    async def receive():return await incoming.get()
    async def send(value):await outgoing.put(value)
    task=asyncio.create_task(TerminalConsumer.as_asgi()(scope,receive,send))
    async def crash_notice():
        try: await task
        except Exception as error: await outgoing.put({"exception":repr(error)})
    asyncio.create_task(crash_notice())
    return incoming,outgoing,task

async def stop(incoming,task):
    await incoming.put({'type':'websocket.disconnect','code':1000})
    await asyncio.wait_for(task,3)

def test_terminal_stream_rejects_cross_origin_and_other_owner(terminal,create_user):
    row,user=terminal
    outsider=User.objects.create(username='ws-outsider-'+uuid4().hex,email=uuid4().hex+'@invalid.example')
    async def scenario():
        for actor,origin in [(user,'http://foreign.invalid'),(SimpleNamespace(is_authenticated=False),'http://testserver'),(outsider,'http://testserver')]:
            incoming,outgoing,task=run_socket(row,actor,origin)
            await incoming.put({'type':'websocket.connect'})
            result=await asyncio.wait_for(outgoing.get(),3)
            assert result['type']=='websocket.close'
            await stop(incoming,task)
    asyncio.run(scenario())

def test_terminal_stream_preserves_input_and_uses_real_output(terminal):
    row,user=terminal
    async def scenario():
        incoming,outgoing,task=run_socket(row,user)
        await incoming.put({'type':'websocket.connect'})
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.accept'
        first=json.loads((await asyncio.wait_for(outgoing.get(),3))['text']);assert first['type']=='output'
        await incoming.put({'type':'websocket.receive','text':json.dumps({'action':'input','data':'Y2Q=','seq':1})})
        ack=json.loads((await asyncio.wait_for(outgoing.get(),3))['text'])
        assert ack=={'type':'ack','seq':1}
        values=await sync_to_async(lambda:list(row.remotecommand_set.filter(payload__kind='terminal_input').values_list('payload',flat=True)))()
        assert values==[{'kind':'terminal_input','session_id':str(row.id),'data':'Y2Q='}]
        await stop(incoming,task)
    asyncio.run(scenario())


def test_stream_rejects_replayed_sequence_without_repeating_input(terminal):
    row,user=terminal
    async def scenario():
        incoming,outgoing,task=run_socket(row,user)
        await incoming.put({'type':'websocket.connect'})
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.accept'
        await asyncio.wait_for(outgoing.get(),3)
        message={'type':'websocket.receive','text':json.dumps({'action':'input','data':'Y2Q=','seq':1})}
        await incoming.put(message)
        assert json.loads((await asyncio.wait_for(outgoing.get(),3))['text'])['type']=='ack'
        await incoming.put(message)
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.close'
        count=await sync_to_async(lambda:row.remotecommand_set.filter(payload__kind='terminal_input').count())()
        assert count==1
        await stop(incoming,task)
    asyncio.run(scenario())


def test_stream_closes_when_device_is_revoked(terminal):
    row,user=terminal
    async def scenario():
        incoming,outgoing,task=run_socket(row,user)
        await incoming.put({'type':'websocket.connect'})
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.accept'
        await asyncio.wait_for(outgoing.get(),3)
        await sync_to_async(lambda:type(row.workstation).objects.filter(pk=row.workstation_id).update(enabled=False))()
        event=await asyncio.wait_for(outgoing.get(),3)
        assert event['type']=='websocket.close' and event['code']==4403
        await stop(incoming,task)
    asyncio.run(scenario())


def test_transport_heartbeat_does_not_repeat_unrelated_admin_membership_sync(remote):
    from unittest.mock import patch
    _,edge,_,_=remote
    with patch('plane.quality.administrator_access.synchronize_administrator_access',side_effect=AssertionError('not part of transport authentication')):
        response=heartbeat(edge)
    assert response.status_code==200


def test_stream_detects_logout_within_next_authorization_check(terminal):
    from importlib import import_module
    from django.conf import settings
    row,user=terminal
    Session=import_module(settings.SESSION_ENGINE).SessionStore
    session=Session();session['_auth_user_id']=str(user.pk);session['_auth_user_backend']=settings.AUTHENTICATION_BACKENDS[0];session['_auth_user_hash']=user.get_session_auth_hash();session.save()
    async def scenario():
        from plane.quality.terminal_stream import TerminalConsumer
        incoming,outgoing=asyncio.Queue(),asyncio.Queue()
        scope={'type':'websocket','url_route':{'kwargs':{'pk':row.id}},'user':user,'session':session,
            'headers':[(b'host',b'testserver'),(b'origin',b'http://testserver')],'query_string':b'','subprotocols':[]}
        async def receive():return await incoming.get()
        async def send(value):await outgoing.put(value)
        task=asyncio.create_task(TerminalConsumer.as_asgi()(scope,receive,send))
        await incoming.put({'type':'websocket.connect'})
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.accept'
        await asyncio.wait_for(outgoing.get(),3)
        await sync_to_async(session.delete)()
        event=await asyncio.wait_for(outgoing.get(),3)
        assert event['type']=='websocket.close'
        await stop(incoming,task)
    asyncio.run(scenario())
