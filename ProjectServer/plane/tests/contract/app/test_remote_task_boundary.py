"""Agent applications work independently of HTTP and preserve device serialization."""

import os
import subprocess
import sys
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from plane.db.models import ProjectMember
from plane.quality.models import Defect
from plane.quality.remote_access import identity_key
from plane.quality.remote_models import (
    RemoteAgentRun,
    RemoteCommand,
    RemoteFeedbackBinding,
    RemoteWorkstation,
)
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_agent_applications_import_without_http_views():
    script = """
import django, sys
django.setup()
sys.modules['plane.quality.remote_diagnostics'] = None
sys.modules['plane.quality.views'] = None
from plane.quality.remote_run_state import invalidate_run, run_queue
from plane.quality.remote_run_requests import create_run, read_run
from plane.quality.remote_tool_operations import execute_tool
from plane.quality.remote_tasks import remote_repair
assert all(callable(value) for value in [invalidate_run, run_queue, create_run, read_run, execute_tool, remote_repair])
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def station_defect(remote):
    _, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title="现场处理边界检查")
    RemoteFeedbackBinding.objects.create(
        workstation=station,
        defect=defect,
        created_by=station.agent.owner,
    )
    return station, defect


def test_direct_create_and_http_share_duplicate_guard_and_dispatch(remote):
    from plane.quality.remote_run_requests import create_run

    client, _, _, _ = remote
    station, defect = station_defect(remote)
    payload = {"device_id": str(station.id), "defect_id": str(defect.id), "problem": "排查"}
    with patch("plane.quality.remote_tasks.remote_repair.apply_async") as dispatch:
        result = create_run(station.agent.owner, payload)
        duplicate = client.post(BASE + "agent-runs/", payload, format="json")
    assert result["status"] == "queued"
    assert duplicate.status_code == 409
    assert RemoteAgentRun.objects.filter(workstation=station, defect=defect).count() == 1
    dispatch.assert_called_once_with(args=[result["id"]], queue="field-repairs")


def test_direct_read_expires_run_and_commands_and_preserves_receipt(remote):
    from plane.quality.remote_run_requests import read_run

    station, defect = station_defect(remote)
    run = RemoteAgentRun.objects.create(
        workstation=station,
        defect=defect,
        owner=station.agent.owner,
        status="running",
        tool_credential_hash="synthetic",
        identity_key=identity_key(station),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    command = RemoteCommand.objects.create(
        workstation=station,
        run=run,
        payload={"kind": "read_file", "path": "config.json"},
        status="delivered",
        expires_at=timezone.now() + timedelta(seconds=30),
    )
    result = read_run(station.agent.owner, run.pk)
    run.refresh_from_db()
    command.refresh_from_db()
    assert result["status"] == "failed" and result["queue"] is None
    assert not run.tool_credential_hash
    assert result["result"]["repaired"] is False
    assert command.status == "expired" and command.payload == {}


def test_direct_tool_revocation_never_dispatches(remote):
    from rest_framework.exceptions import PermissionDenied
    from plane.quality.remote_tool_operations import execute_tool

    station, defect = station_defect(remote)
    station.capabilities["agent_context"] = {
        "repair_allowed": True,
        "inspect_argv": ["/usr/bin/inspect-simulation"],
    }
    station.save(update_fields=["capabilities"])
    run = RemoteAgentRun.objects.create(
        workstation=station,
        defect=defect,
        owner=station.agent.owner,
        status="running",
        identity_key=identity_key(station),
        expires_at=timezone.now() + timedelta(minutes=1),
    )
    ProjectMember.objects.filter(project=defect.project, member=station.agent.owner).update(is_active=False)
    with patch("plane.quality.remote_tool_operations.command") as dispatch:
        with pytest.raises(PermissionDenied):
            execute_tool(run, {"operation": "run", "argv": ["/usr/bin/inspect-simulation"]})
    dispatch.assert_not_called()


def test_direct_create_failure_does_not_queue_or_persist_a_run(remote):
    from rest_framework.exceptions import ValidationError
    from plane.quality.remote_run_requests import create_run

    station, defect = station_defect(remote)
    with patch("plane.quality.remote_tasks.remote_repair.apply_async") as dispatch:
        with pytest.raises(ValidationError):
            create_run(
                station.agent.owner,
                {
                    "device_id": str(station.id),
                    "defect_id": str(defect.id),
                    "problem": "排查",
                    "mode": "unsupported",
                },
            )
    assert not RemoteAgentRun.objects.filter(workstation=station).exists()
    dispatch.assert_not_called()
