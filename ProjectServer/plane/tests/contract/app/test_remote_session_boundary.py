"""HTTP and WebSocket use one transaction-aware terminal application boundary."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from plane.db.models import ProjectMember
from plane.quality.remote_models import RemoteTerminal
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_session_application_imports_without_http_views():
    script = "import django,sys; django.setup(); "
    script += "sys.modules['plane.quality.remote_diagnostics']=None; sys.modules['plane.quality.views']=None; "
    script += "from plane.quality.remote_sessions import open_session,read_session,change_session,close_session; "
    script += "assert all(callable(value) for value in [open_session,read_session,change_session,close_session])"
    result = subprocess.run(
        [sys.executable, "-c", script], env=os.environ.copy(), capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


def test_websocket_input_does_not_construct_or_call_a_http_view(remote):
    from plane.quality.terminal_stream import session_request

    client, edge, device, _ = remote
    heartbeat(edge)
    opened = client.post(BASE, {"action": "open", "device_id": device}, format="json")
    sid = opened.data["id"]
    owner = RemoteTerminal.objects.get(pk=sid).owner
    with patch("plane.quality.remote_diagnostics.RemoteSession.get", side_effect=AssertionError("HTTP adapter")):
        with patch("plane.quality.remote_diagnostics.RemoteSession.post", side_effect=AssertionError("HTTP adapter")):
            status, value = asyncio.run(session_request(owner, sid, {"action": "input", "data": "Y2Q="}))
            assert status == 200 and value == {"accepted": True}
            status, value = asyncio.run(session_request(owner, sid))
            assert status == 200 and value["status"] == "open"


def test_direct_and_http_input_have_same_payload_and_validation(remote):
    from plane.quality.remote_sessions import change_session

    client, edge, device, _ = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action": "open", "device_id": device}, format="json").data["id"]
    row = RemoteTerminal.objects.get(pk=sid)
    direct = change_session(row.owner, sid, {"action": "input", "data": "YQ=="})
    response = client.post(BASE + "sessions/" + sid + "/", {"action": "input", "data": "YQ=="}, format="json")
    assert (direct.status_code, direct.data) == (response.status_code, response.data)
    commands = list(row.remotecommand_set.filter(payload__kind="terminal_input").values_list("payload", flat=True))
    assert commands == [{"kind": "terminal_input", "session_id": sid, "data": "YQ=="}] * 2


def test_direct_revoke_returns_denial_but_commits_terminal_close(remote):
    from plane.quality.remote_sessions import change_session

    client, edge, device, project = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action": "open", "device_id": device}, format="json").data["id"]
    row = RemoteTerminal.objects.get(pk=sid)
    ProjectMember.objects.filter(project=project, member=row.owner).update(is_active=False)
    result = change_session(row.owner, sid, {"action": "input", "data": "YQ=="})
    assert result.status_code == 403
    row.refresh_from_db()
    assert row.status == "closed"
    assert not row.remotecommand_set.filter(payload__kind="terminal_input").exists()
    assert row.remotecommand_set.filter(payload__kind="terminal_close").count() == 1


def test_invalid_open_dimensions_roll_back_session_and_command(remote):
    from plane.quality.remote_sessions import open_session
    from rest_framework.exceptions import ValidationError

    _, edge, device, _ = remote
    heartbeat(edge)
    from plane.quality.remote_models import RemoteWorkstation

    station = RemoteWorkstation.objects.get(pk=device)
    with pytest.raises(ValidationError):
        open_session(station.agent.owner, {"device_id": device, "cols": 1})
    assert station.remoteterminal_set.count() == 0
    assert station.commands.count() == 0


def test_simultaneous_http_and_websocket_inputs_share_the_existing_backpressure_limit(remote):
    from django.db import close_old_connections
    from plane.quality.remote_models import RemoteCommand
    from plane.quality.remote_sessions import change_session
    from plane.quality.terminal_stream import session_request

    client, edge, device, _ = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action": "open", "device_id": device}, format="json").data["id"]
    row = RemoteTerminal.objects.get(pk=sid)
    # Existing contract rejects when more than 100 commands are already pending.
    RemoteCommand.objects.bulk_create(
        [
            RemoteCommand(
                workstation=row.workstation, session=row, payload={"kind": "terminal_resize"}, expires_at=row.expires_at
            )
            for _ in range(99)
        ]
    )

    def submit(mode):
        try:
            if mode == "websocket":
                return asyncio.run(session_request(row.owner, sid, {"action": "input", "data": "YQ=="}))[0]
            return change_session(row.owner, sid, {"action": "input", "data": "YQ=="}).status_code
        except Exception as error:
            return getattr(error, "status_code", None)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, ["http", "websocket"]))
    assert sorted(results) == [200, 409]
    assert row.remotecommand_set.filter(payload__kind="terminal_input").count() == 1


def test_open_quota_remains_serialized_between_concurrent_application_callers(remote):
    from django.db import close_old_connections
    from plane.quality.remote_models import RemoteWorkstation
    from plane.quality.remote_sessions import open_session

    _, edge, device, _ = remote
    heartbeat(edge)
    owner = RemoteWorkstation.objects.get(pk=device).agent.owner

    def open_one(_index):
        try:
            return open_session(owner, {"device_id": device}).status_code
        except Exception as error:
            return getattr(error, "status_code", None)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(open_one, range(4)))
    assert sorted(results) == [201, 201, 409, 409]
    assert RemoteTerminal.objects.filter(workstation_id=device, status="open").count() == 2


def test_shared_session_reads_current_snapshot_with_one_less_database_roundtrip(remote):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from plane.quality.remote_sessions import read_session, change_session

    client, edge, device, _ = remote
    heartbeat(edge)
    sid = client.post(BASE, {"action": "open", "device_id": device}, format="json").data["id"]
    owner = RemoteTerminal.objects.get(pk=sid).owner
    with CaptureQueriesContext(connection) as read_queries:
        assert read_session(owner, sid).status_code == 200
    with CaptureQueriesContext(connection) as input_queries:
        assert change_session(owner, sid, {"action": "input", "data": "YQ=="}).status_code == 200
    assert len(read_queries) <= 12
    assert len(input_queries) <= 12
