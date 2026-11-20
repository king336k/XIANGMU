"""Bound real terminal cache writes without changing durable or authorization paths."""

import asyncio
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django_redis import get_redis_connection

from plane.quality.terminal_stream import fast_output, publish_fast_output

pytest_plugins = ['plane.tests.contract.app.test_terminal_stream']
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def events(row, count=8, prefix='batch'):
    return [{'session_id': str(row.id), 'kind': 'data', 'id': f'{prefix}-{index}',
             'data': base64.b64encode(f'{prefix}-{index}\r\n'.encode()).decode()}
            for index in range(count)]


def test_empty_output_heartbeat_never_opens_redis_or_reads_sessions():
    with patch('django_redis.get_redis_connection') as redis:
        with patch('plane.quality.remote_models.RemoteTerminal.objects.filter') as sessions:
            asyncio.run(publish_fast_output('unused-station', []))
    redis.assert_not_called()
    sessions.assert_not_called()


def test_batch_uses_one_redis_roundtrip_without_per_event_increments(terminal):
    row, _ = terminal
    client = get_redis_connection('default')
    pipeline = client.pipeline(transaction=False)
    with patch.object(client, 'execute_command', wraps=client.execute_command) as direct:
        with patch.object(pipeline, 'execute', wraps=pipeline.execute) as batched:
            with patch.object(client, 'pipeline', return_value=pipeline):
                with patch('django_redis.get_redis_connection', return_value=client):
                    asyncio.run(publish_fast_output(row.workstation_id, events(row)))
    assert direct.call_count == 0, 'terminal output still incurs a Redis roundtrip per event'
    assert batched.call_count == 1
    values = asyncio.run(fast_output(row.id))
    assert [value['source_id'] for value in values] == [f'batch-{index}' for index in range(8)]
    assert [value['fast_seq'] for value in values] == list(range(1, 9))


def test_cache_remains_bounded_and_expires_without_touching_durable_history(terminal):
    row, _ = terminal
    client = get_redis_connection('default')
    asyncio.run(publish_fast_output(row.workstation_id, events(row, 100)))
    key = 'remote:terminal-output:' + str(row.id)
    assert client.llen(key) == 8
    values = asyncio.run(fast_output(row.id))
    assert [value['fast_seq'] for value in values] == list(range(93, 101))
    assert 0 < client.ttl(key) <= 60
    assert 0 < client.ttl(key + ':seq') <= 120
    assert not row.events.exists()


def test_batch_reuses_only_its_current_session_authorization(terminal):
    from plane.db.models import ProjectMember
    from plane.quality.remote_access import permitted

    row, _ = terminal
    with patch('plane.quality.remote_access.permitted', wraps=permitted) as decision:
        asyncio.run(publish_fast_output(row.workstation_id, events(row, 100)))
    assert decision.call_count == 1, 'same session rechecks identical membership per output'
    ProjectMember.objects.filter(project_id=row.workstation.agent.project_id, member=row.owner).update(is_active=False)
    asyncio.run(publish_fast_output(row.workstation_id, events(row, 1, 'revoked')))
    assert all(value['source_id'] != 'revoked-0' for value in asyncio.run(fast_output(row.id)))


def test_same_batch_never_borrows_another_session_owners_permission(terminal):
    from datetime import timedelta
    from uuid import uuid4
    from django.utils import timezone
    from plane.db.models import ProjectMember, User, WorkspaceMember
    from plane.license.models import Instance, InstanceAdmin
    from plane.quality.remote_models import RemoteTerminal

    row, _ = terminal
    project = row.workstation.agent.project
    user = User.objects.create(username='other-' + uuid4().hex, email=uuid4().hex + '@invalid.test')
    WorkspaceMember.objects.create(workspace=project.workspace, member=user, role=20)
    membership = ProjectMember.objects.create(project=project, member=user, role=20, is_active=False)
    InstanceAdmin.objects.create(instance=Instance.objects.first(), user=user)
    other = RemoteTerminal.objects.create(workstation=row.workstation, owner=user,
                                         expires_at=timezone.now() + timedelta(minutes=1), last_read_at=timezone.now())
    asyncio.run(publish_fast_output(row.workstation_id, events(row, 1) + events(other, 1, 'other')))
    assert asyncio.run(fast_output(row.id))
    assert asyncio.run(fast_output(other.id)) == []
    membership.is_active = True
    membership.save(update_fields=['is_active'])
    asyncio.run(publish_fast_output(row.workstation_id, events(other, 1, 'allowed')))
    assert asyncio.run(fast_output(other.id))[0]['source_id'] == 'allowed-0'


def test_simultaneous_producers_keep_cache_list_in_sequence_order(terminal):
    row, _ = terminal
    client = get_redis_connection('default')

    def produce(number):
        # Bypass the async adapter so independent worker threads really overlap.
        from django.db import close_old_connections

        try:
            publish_fast_output.__wrapped__(row.workstation_id, events(row, 8, f'writer-{number}'))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(produce, range(4)))
    key = 'remote:terminal-output:' + str(row.id)
    values = [json.loads(raw) for raw in client.lrange(key, 0, -1)]
    assert [value['fast_seq'] for value in values] == list(range(25, 33))
    assert int(client.get(key + ':seq')) == 32


def test_unavailable_fast_cache_still_allows_durable_exchange(terminal, remote):
    from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

    row, _ = terminal
    client, edge, _, _ = remote
    output = events(row, 1)[0]
    with patch('django_redis.get_redis_connection', side_effect=ConnectionError('isolated cache outage')):
        asyncio.run(publish_fast_output(row.workstation_id, [output]))
        assert asyncio.run(fast_output(row.id)) == []
    response = heartbeat(edge, outputs=[output])
    assert response.status_code == 200
    history = client.get(BASE + 'sessions/' + str(row.id) + '/')
    assert history.status_code == 200
    assert history.data['events'][0]['source_id'] == output['id']
