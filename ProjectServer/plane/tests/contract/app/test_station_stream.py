import asyncio,json
import pytest
from plane.tests.contract.app.test_remote_diagnostics import BASE,heartbeat
from plane.quality.remote_models import RemoteWorkstation
pytest_plugins=['plane.tests.contract.app.test_remote_diagnostics']
pytestmark=[pytest.mark.contract,pytest.mark.django_db(transaction=True)]

async def socket(headers):
    from plane.quality.terminal_stream import StationConsumer
    incoming,outgoing=asyncio.Queue(),asyncio.Queue()
    async def receive():return await incoming.get()
    async def send(v):await outgoing.put(v)
    scope={'type':'websocket','headers':headers,'path':'/api/quality-auth/remote-diagnostics/station-stream/','query_string':b'','subprotocols':[]}
    task=asyncio.create_task(StationConsumer.as_asgi()(scope,receive,send))
    await incoming.put({'type':'websocket.connect'})
    return incoming,outgoing,task

@pytest.mark.parametrize('headers',[[],[(b'authorization',b'Bearer rw_wrong')],[(b'authorization',b'Bearer rw_test'),(b'origin',b'http://testserver')]])
def test_station_stream_requires_device_credential_and_rejects_browser_origin(headers):
    async def scenario():
        incoming,outgoing,task=await socket(headers)
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.close'
        await incoming.put({'type':'websocket.disconnect','code':1000});await asyncio.wait_for(task,3)
    asyncio.run(scenario())

def test_station_stream_acks_batches_and_keeps_credential_out_of_messages(remote):
    client,edge,device,project=remote
    token=edge._credentials['HTTP_AUTHORIZATION']
    async def scenario():
        incoming,outgoing,task=await socket([(b'authorization',token.encode())])
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.accept'
        assert json.loads((await outgoing.get())['text'])=={'type':'ready'}
        payload={'identity':{'username':'stream','hostname':'test','boot_id':'boot'},'outputs':[],'results':[]}
        await incoming.put({'type':'websocket.receive','text':json.dumps({'seq':1,'payload':payload})})
        result=json.loads((await asyncio.wait_for(outgoing.get(),3))['text'])
        assert result=={'type':'exchange','seq':1,'commands':[]}
        assert token not in json.dumps(result)
        await incoming.put({'type':'websocket.receive','text':json.dumps({'seq':1,'payload':payload})})
        assert (await asyncio.wait_for(outgoing.get(),3))['type']=='websocket.close'
        await incoming.put({'type':'websocket.disconnect','code':1000});await asyncio.wait_for(task,3)
    asyncio.run(scenario())


def test_station_command_is_pushed_without_waiting_for_next_heartbeat(remote):
    from asgiref.sync import sync_to_async
    from plane.quality.remote_models import RemoteCommand
    from django.utils import timezone
    from datetime import timedelta
    client,edge,device,project=remote;token=edge._credentials['HTTP_AUTHORIZATION']
    async def scenario():
        incoming,outgoing,task=await socket([(b'authorization',token.encode())])
        await outgoing.get();await outgoing.get()
        payload={'identity':{'username':'push','hostname':'test','boot_id':'boot'},'outputs':[],'results':[]}
        await incoming.put({'type':'websocket.receive','text':json.dumps({'seq':1,'payload':payload})})
        await outgoing.get()
        await sync_to_async(RemoteCommand.objects.create)(workstation_id=device,payload={'kind':'terminal_resize','session_id':'test','cols':80,'rows':24},expires_at=timezone.now()+timedelta(seconds=10))
        response=json.loads((await asyncio.wait_for(outgoing.get(),3))['text'])
        assert response['type']=='commands' and response['commands'][0]['kind']=='terminal_resize'
        await incoming.put({'type':'websocket.disconnect','code':1000});await asyncio.wait_for(task,3)
    asyncio.run(scenario())


def test_station_stream_delivers_real_terminal_input_and_output_roundtrip(remote):
    from asgiref.sync import sync_to_async
    import base64
    client,edge,device,project=remote;token=edge._credentials['HTTP_AUTHORIZATION'];heartbeat(edge)
    opened=client.post(BASE,{'action':'open','device_id':device,'cols':80,'rows':24},format='json')
    sid=opened.data['id']
    async def scenario():
        incoming,outgoing,task=await socket([(b'authorization',token.encode())]);await outgoing.get();await outgoing.get()
        payload={'identity':{'username':'caozuo1','hostname':'operator195','boot_id':'boot1'},'outputs':[],'results':[]}
        await incoming.put({'type':'websocket.receive','text':json.dumps({'seq':1,'payload':payload})})
        first=json.loads((await asyncio.wait_for(outgoing.get(),3))['text']);assert first['commands'][0]['kind']=='terminal_open'
        opened_id=first['commands'][0]['id']
        await sync_to_async(client.post)(BASE+'sessions/'+sid+'/',{'action':'input','data':'Y2Q='},format='json')
        commands=json.loads((await asyncio.wait_for(outgoing.get(),3))['text']);assert commands['type']=='commands'
        assert any(row['kind']=='terminal_input' for row in commands['commands'])
        output={'session_id':sid,'kind':'data','id':'stream-output','data':base64.b64encode(b'actual output').decode()}
        await incoming.put({'type':'websocket.receive','text':json.dumps({'seq':2,'payload':{**payload,'outputs':[output],'results':[{'id':opened_id,'ok':True},{'id':next(row['id']for row in commands['commands']if row['kind']=='terminal_input'),'ok':True}]}})})
        assert json.loads((await asyncio.wait_for(outgoing.get(),3))['text'])['seq']==2
        read=await sync_to_async(client.get)(BASE+'sessions/'+sid+'/')
        assert base64.b64decode(read.data['events'][0]['data'])==b'actual output'
        await incoming.put({'type':'websocket.disconnect','code':1000});await asyncio.wait_for(task,3)
    asyncio.run(scenario())


def test_stream_exchange_delivers_close_for_already_closed_session(remote):
    from plane.quality.remote_models import RemoteTerminal
    from plane.quality.remote_diagnostics import close_session
    from plane.quality.terminal_stream import station_exchange
    client,edge,device,project=remote;heartbeat(edge)
    opened=client.post(BASE,{'action':'open','device_id':device,'cols':80,'rows':24},format='json')
    row=RemoteTerminal.objects.get(pk=opened.data['id']);close_session(row)
    token=edge._credentials['HTTP_AUTHORIZATION'].removeprefix('Bearer ')
    status,result=asyncio.run(station_exchange(token,{'identity':{'username':'caozuo1','hostname':'operator195','boot_id':'boot1'},'outputs':[],'results':[]}))
    assert status==200 and any(c['kind']=='terminal_close'for c in result['commands'])
    assert not any(c['kind']=='terminal_open'for c in result['commands'])


def test_ten_station_streams_keep_commands_and_output_isolated(remote):
    from asgiref.sync import sync_to_async
    client,edge,device,project=remote
    credentials=[]
    for index in range(10):
        row=client.post(BASE,{'action':'register','project_id':str(project.id),'name':f'parallel-{index}'},format='json')
        assert row.status_code==201
        credentials.append('Bearer '+row.data['token'])
    async def one(index,credential):
        incoming,outgoing,task=await socket([(b'authorization',credential.encode())])
        assert (await asyncio.wait_for(outgoing.get(),10))['type']=='websocket.accept'
        assert json.loads((await asyncio.wait_for(outgoing.get(),10))['text'])['type']=='ready'
        payload={'identity':{'username':f'user-{index}','hostname':f'host-{index}','boot_id':'boot'},'outputs':[],'results':[]}
        for seq in range(1,6):
            await incoming.put({'type':'websocket.receive','text':json.dumps({'seq':seq,'payload':payload})})
            ack=json.loads((await asyncio.wait_for(outgoing.get(),10))['text'])
            assert ack=={'type':'exchange','seq':seq,'commands':[]}
        await incoming.put({'type':'websocket.disconnect','code':1000});await asyncio.wait_for(task,10)
    async def scenario():await asyncio.gather(*(one(index,token)for index,token in enumerate(credentials)))
    asyncio.run(scenario())
    assert RemoteWorkstation.objects.filter(username__startswith='user-',hostname__startswith='host-').count()==10
