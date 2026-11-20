"""A server push must not replay an old socket's device observation as a new heartbeat."""
import asyncio
import json
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from plane.quality.models import Defect
from plane.quality.remote_diagnostics import identity_key
from plane.quality.remote_models import RemoteAgentRun, RemoteCommand, RemoteTerminal, RemoteWorkstation
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat
from plane.tests.contract.app.test_station_stream import socket

pytest_plugins = ['plane.tests.contract.app.test_remote_diagnostics']
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def observation(executor=None):
    terminal = {'ready': True}
    if executor:
        terminal['executor_instance'] = executor
    return {'username': 'operator', 'hostname': 'same-computer', 'boot_id': 'same-boot',
            'capabilities': {'terminal': terminal, 'robot': {'connected': False}}}


def test_old_socket_push_cannot_roll_back_new_executor_or_close_new_terminal(remote):
    client, edge, device, _ = remote
    token = edge._credentials['HTTP_AUTHORIZATION']

    async def scenario():
        incoming, outgoing, task = await socket([(b'authorization', token.encode())])
        await outgoing.get()
        await outgoing.get()
        await incoming.put({'type': 'websocket.receive', 'text': json.dumps({
            'seq': 1, 'payload': {'identity': observation(), 'outputs': [], 'results': []}})})
        await asyncio.wait_for(outgoing.get(), 3)
        try:
            assert (await sync_to_async(heartbeat)(edge, identity=observation('a' * 32))).status_code == 200
            opened = await sync_to_async(client.post)(
                BASE, {'action': 'open', 'device_id': device}, format='json')
            assert opened.status_code == 201
            session_id = opened.data['id']
            # Wakes the old socket's server-side push loop with its cached identity.
            await asyncio.wait_for(outgoing.get(), 3)
            await asyncio.sleep(.1)
            station = await sync_to_async(RemoteWorkstation.objects.get)(pk=device)
            session = await sync_to_async(RemoteTerminal.objects.get)(pk=session_id)
            assert station.capabilities.get('terminal', {}).get('executor_instance') == 'a' * 32
            assert session.status == 'open'
        finally:
            await incoming.put({'type': 'websocket.disconnect', 'code': 1000})
            await asyncio.wait_for(task, 3)
    asyncio.run(scenario())


def test_old_socket_push_never_invalidates_new_running_agent(remote):
    _, edge, device, project = remote
    token = edge._credentials['HTTP_AUTHORIZATION']

    async def scenario():
        incoming, outgoing, task = await socket([(b'authorization', token.encode())])
        await outgoing.get()
        await outgoing.get()
        await incoming.put({'type': 'websocket.receive', 'text': json.dumps({
            'seq': 1, 'payload': {'identity': observation(), 'outputs': [], 'results': []}})})
        await asyncio.wait_for(outgoing.get(), 3)
        await sync_to_async(heartbeat)(edge, identity=observation('b' * 32))

        def create_task():
            station = RemoteWorkstation.objects.get(pk=device)
            defect = Defect.objects.create(project=project, title='stale transport probe')
            run = RemoteAgentRun.objects.create(workstation=station, defect=defect, owner=station.agent.owner,
                status='running', identity_key=identity_key(station), expires_at=timezone.now() + timedelta(minutes=1))
            command = RemoteCommand.objects.create(workstation=station, run=run,
                payload={'kind': 'run', 'argv': ['fixed-readonly-inspection']}, expires_at=run.expires_at)
            return run.pk, command.pk

        run_id, command_id = await sync_to_async(create_task)()
        try:
            # The old implementation expires the task before it can push it.
            await asyncio.sleep(.3)
            run = await sync_to_async(RemoteAgentRun.objects.get)(pk=run_id)
            command = await sync_to_async(RemoteCommand.objects.get)(pk=command_id)
            assert run.status == 'running'
            assert command.status == 'pending'  # A replaced connection cannot consume it.
        finally:
            await incoming.put({'type': 'websocket.disconnect', 'code': 1000})
            await asyncio.wait_for(task, 3)
    asyncio.run(scenario())


def test_server_poll_preserves_new_robot_observation_and_heartbeat_time(remote):
    from plane.quality.terminal_stream import station_exchange

    _, edge, device, _ = remote
    old = observation('a' * 32)
    assert heartbeat(edge, identity=old).status_code == 200
    fresh = observation('a' * 32)
    fresh['capabilities']['robot'] = {'connected': True, 'username': 'robot', 'host': '10.2.0.1',
                                    'target_revision': 'b' * 64}
    assert heartbeat(edge, identity=fresh).status_code == 200
    before = RemoteWorkstation.objects.get(pk=device)
    status, _ = asyncio.run(station_exchange(
        edge._credentials['HTTP_AUTHORIZATION'].removeprefix('Bearer '),
        {'identity': old, 'outputs': [], 'results': []}, previous_identity=old, poll_only=True))
    after = RemoteWorkstation.objects.get(pk=device)
    assert status == 200
    assert after.capabilities == before.capabilities
    assert after.last_seen_at == before.last_seen_at


@pytest.mark.parametrize('first_frame', [False, True])
def test_delayed_old_socket_frame_cannot_replace_new_executor(remote, first_frame):
    _, edge, device, _ = remote
    token = edge._credentials['HTTP_AUTHORIZATION']

    async def scenario():
        incoming, outgoing, task = await socket([(b'authorization', token.encode())])
        await outgoing.get()
        await outgoing.get()
        try:
            if not first_frame:
                await incoming.put({'type': 'websocket.receive', 'text': json.dumps({
                    'seq': 1, 'payload': {'identity': observation(), 'outputs': [], 'results': []}})})
                await asyncio.wait_for(outgoing.get(), 3)
            await sync_to_async(heartbeat)(edge, identity=observation('c' * 32))
            await incoming.put({'type': 'websocket.receive', 'text': json.dumps({
                'seq': 1 if first_frame else 2,
                'payload': {'identity': observation(), 'outputs': [], 'results': []}})})
            assert (await asyncio.wait_for(outgoing.get(), 3))['type'] == 'websocket.close'
            station = await sync_to_async(RemoteWorkstation.objects.get)(pk=device)
            assert station.capabilities['terminal']['executor_instance'] == 'c' * 32
        finally:
            await incoming.put({'type': 'websocket.disconnect', 'code': 1000})
            await asyncio.wait_for(task, 3)
    asyncio.run(scenario())


def test_server_poll_cannot_keep_an_offline_executor_alive(remote):
    from plane.quality.terminal_stream import station_exchange

    _, edge, device, _ = remote
    identity = observation('d' * 32)
    heartbeat(edge, identity=identity)
    old_time = timezone.now() - timedelta(seconds=31)
    RemoteWorkstation.objects.filter(pk=device).update(last_seen_at=old_time)
    status, _ = asyncio.run(station_exchange(
        edge._credentials['HTTP_AUTHORIZATION'].removeprefix('Bearer '),
        {'identity': identity, 'outputs': [], 'results': []}, previous_identity=identity, poll_only=True))
    assert status == 409
    assert RemoteWorkstation.objects.get(pk=device).last_seen_at == old_time


def test_overlapping_reconnect_of_same_executor_keeps_its_new_terminal(remote):
    client, edge, device, _ = remote
    token = edge._credentials['HTTP_AUTHORIZATION']

    async def scenario():
        # Both sockets handshake before the new executor's first observation.
        old_in, old_out, old_task = await socket([(b'authorization', token.encode())])
        new_in, new_out, new_task = await socket([(b'authorization', token.encode())])
        await old_out.get()
        await old_out.get()
        await new_out.get()
        await new_out.get()
        payload = {'identity': observation('e' * 32), 'outputs': [], 'results': []}
        try:
            await old_in.put({'type': 'websocket.receive', 'text': json.dumps({'seq': 1, 'payload': payload})})
            assert json.loads((await asyncio.wait_for(old_out.get(), 3))['text'])['type'] == 'exchange'
            opened = await sync_to_async(client.post)(BASE, {'action': 'open', 'device_id': device}, format='json')
            assert opened.status_code == 201
            await new_in.put({'type': 'websocket.receive', 'text': json.dumps({'seq': 1, 'payload': payload})})
            assert json.loads((await asyncio.wait_for(new_out.get(), 3))['text'])['type'] == 'exchange'
            row = await sync_to_async(RemoteTerminal.objects.get)(pk=opened.data['id'])
            assert row.status == 'open'
        finally:
            for incoming, task in [(old_in, old_task), (new_in, new_task)]:
                await incoming.put({'type': 'websocket.disconnect', 'code': 1000})
                await asyncio.wait_for(task, 3)
    asyncio.run(scenario())


def test_http_body_cannot_claim_server_poll_to_bypass_real_restart(remote):
    client, edge, device, _ = remote
    heartbeat(edge, identity=observation('f' * 32))
    opened = client.post(BASE, {'action': 'open', 'device_id': device}, format='json')
    assert opened.status_code == 201
    assert heartbeat(edge, identity=observation('a' * 32), remote_stream_poll_only=True,
                     remote_stream_previous_identity=observation('a' * 32)).status_code == 200
    assert RemoteTerminal.objects.get(pk=opened.data['id']).status == 'closed'
    assert RemoteWorkstation.objects.filter(pk=device).count() == 1
