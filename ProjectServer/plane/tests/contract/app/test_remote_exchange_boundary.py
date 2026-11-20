"""Shared exchange accepts real device traffic without instantiating HTTP views."""

import asyncio
from datetime import timedelta
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from django.utils import timezone
from plane.quality.remote_models import RemoteWorkstation
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_exchange_and_directory_import_without_http_adapters():
    script = """
import django,sys
django.setup()
for name in ['remote_diagnostics','remote_files','views']:
    sys.modules['plane.quality.'+name]=None
from plane.quality.remote_exchange import authenticate_station,exchange_station
from plane.quality.remote_directory import list_devices,change_directory,list_feedback,list_defect_targets
assert all(callable(value) for value in [authenticate_station,exchange_station,list_devices,change_directory,list_feedback,list_defect_targets])
"""
    result = subprocess.run(
        [sys.executable, "-c", script], env=os.environ.copy(), capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


def test_station_websocket_exchange_never_constructs_http_view(remote):
    from plane.quality.terminal_stream import station_exchange, station_identity
    from plane.quality.remote_exchange import exchange_station

    _, edge, device, _ = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    token = edge._credentials["HTTP_AUTHORIZATION"].removeprefix("Bearer ")
    identity = {
        "username": station.username,
        "hostname": station.hostname,
        "boot_id": station.boot_id,
        "capabilities": station.capabilities,
    }
    with patch("plane.quality.remote_diagnostics.RemoteExchange.as_view", side_effect=AssertionError("HTTP view")):
        status, value = asyncio.run(station_exchange(token, {"identity": identity, "outputs": [], "results": []}))
        assert (
            status == 200
            and value == exchange_station(device, {"identity": identity, "outputs": [], "results": []}).data
        )
        assert asyncio.run(station_identity(token)) == device


def test_command_poll_does_not_refresh_observation_and_rejects_stale_device(remote):
    from plane.quality.remote_exchange import exchange_station

    _, edge, device, _ = remote
    heartbeat(edge)
    before = RemoteWorkstation.objects.get(pk=device)
    result = exchange_station(
        device, {"identity": {"username": "ignored"}, "outputs": [], "results": []}, poll_only=True
    )
    after = RemoteWorkstation.objects.get(pk=device)
    assert result.status_code == 200
    assert (after.username, after.capabilities, after.last_seen_at) == (
        before.username,
        before.capabilities,
        before.last_seen_at,
    )
    RemoteWorkstation.objects.filter(pk=device).update(last_seen_at=timezone.now() - timedelta(seconds=25))
    assert exchange_station(device, {}, poll_only=True).status_code == 409


def test_directory_application_and_http_use_same_device_cards(remote):
    from plane.quality.remote_directory import list_devices

    client, edge, _, _ = remote
    heartbeat(edge)
    response = client.get(BASE)
    owner = RemoteWorkstation.objects.first().agent.owner
    result = list_devices(owner, {})
    assert response.status_code == result.status_code == 200
    assert response.data == result.data


@pytest.mark.parametrize('field', ['results', 'outputs'])
def test_malformed_uuid_exchange_matches_http_error_and_rolls_back_observation(remote, field):
    from plane.quality.terminal_stream import station_exchange

    _, edge, device, _ = remote
    heartbeat(edge)
    token = edge._credentials['HTTP_AUTHORIZATION'].removeprefix('Bearer ')
    before = RemoteWorkstation.objects.get(pk=device)
    payload = {'identity': {'username': 'must-rollback', 'hostname': before.hostname, 'boot_id': before.boot_id},
               'results': [], 'outputs': []}
    payload[field] = [{'id': 'bad-id'}] if field == 'results' else [{'session_id': 'bad-id', 'kind': 'data'}]
    response = edge.post(BASE + 'exchange/', payload, format='json')
    status, body = asyncio.run(station_exchange(token, payload))
    assert response.status_code == status == 400
    assert body == response.data
    after = RemoteWorkstation.objects.get(pk=device)
    assert (after.username, after.last_seen_at) == (before.username, before.last_seen_at)
