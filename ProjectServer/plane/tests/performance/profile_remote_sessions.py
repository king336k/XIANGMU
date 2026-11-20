"""Explicit paired measurement of the old view bridge and shared session service.

SESSION_BASELINE_ROOT points to preserved remote_diagnostics-before.py and
terminal_stream-before.py. SESSION_PROFILE_REPORT is an artifact JSON path.
Run explicitly with pytest; this module is not part of ordinary test discovery.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import statistics
import time

from asgiref.sync import sync_to_async
from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from plane.quality import remote_diagnostics, terminal_stream
from plane.quality.remote_models import RemoteTerminal
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins = ['plane.tests.contract.app.test_remote_diagnostics']
pytestmark = [pytest.mark.contract, pytest.mark.slow, pytest.mark.django_db(transaction=True)]


def load(name, path):
    spec = importlib.util.spec_from_file_location('plane.quality.' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paired_session_adapters(remote):
    client, edge, device, _ = remote
    heartbeat(edge)
    sid = client.post(BASE, {'action': 'open', 'device_id': device}, format='json').data['id']
    session = RemoteTerminal.objects.get(pk=sid)
    owner = session.owner
    before = Path(os.environ['SESSION_BASELINE_ROOT'])
    previous_view = load('profile_old_http', before / 'remote_diagnostics-before.py')
    previous_stream = load('profile_old_stream', before / 'terminal_stream-before.py')
    previous_stream.RemoteSession = previous_view.RemoteSession
    timings = {}

    async def compare(operation):
        samples = {'before': [], 'after': []}
        for index in range(68):
            order = [('before', previous_stream.session_request), ('after', terminal_stream.session_request)]
            if index % 2:
                order.reverse()
            for label, call in order:
                action = None if operation == 'read' else {'action': 'input', 'data': 'YQ=='}
                start = time.perf_counter_ns()
                status, data = await call(owner, sid, action)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                assert status == 200
                assert data.get('status') == 'open' if action is None else data == {'accepted': True}
                if index >= 8:
                    samples[label].append(elapsed)
                await sync_to_async(lambda: session.remotecommand_set.filter(status='pending').update(status='done'))()
        return {name: {'n': len(values), 'median_ms': statistics.median(values),
                       'p95_ms': sorted(values)[int(len(values)*.95)-1], 'samples_ms': values}
                for name, values in samples.items()}

    for operation in ['read', 'input']:
        timings[operation] = asyncio.run(compare(operation))
    factory = APIRequestFactory()
    queries = {}
    for name, view in [('before', previous_view.RemoteSession), ('after', remote_diagnostics.RemoteSession)]:
        request = factory.get('/')
        force_authenticate(request, user=owner)
        with CaptureQueriesContext(connection) as captured:
            result = view.as_view()(request, pk=sid)
        assert result.status_code == 200
        queries[name] = len(captured)
    Path(os.environ['SESSION_PROFILE_REPORT']).write_text(json.dumps({
        'scope': 'isolated_same_database_websocket_application_path', 'query_counts_http_read': queries,
        'alternating_order': True, 'timings': timings}, indent=2))
