"""Executor restarts replace transient sessions, never the persistent computer card."""

from plane.quality.remote_models import RemoteTerminal, RemoteWorkstation
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat
import pytest

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def observed(executor):
    terminal = {"ready": True}
    if executor is not None:
        terminal["executor_instance"] = executor
    return {
        "username": "operator",
        "hostname": "same-computer",
        "boot_id": "same-os-boot",
        "capabilities": {"terminal": terminal, "file_browser": {"ready": True}},
    }


def test_executor_restart_closes_both_stale_terminals_and_keeps_one_card(remote):
    client, edge, device, _ = remote
    assert heartbeat(edge, identity=observed("a" * 32)).status_code == 200
    opened = [client.post(BASE, {"action": "open", "device_id": device}, format="json") for _ in range(2)]
    assert all(response.status_code == 201 for response in opened)
    ids = [response.data["id"] for response in opened]
    assert heartbeat(edge, identity=observed("b" * 32)).status_code == 200
    assert not RemoteTerminal.objects.filter(pk__in=ids, status="open").exists()
    assert client.post(BASE, {"action": "open", "device_id": device}, format="json").status_code == 201
    assert RemoteWorkstation.objects.filter(pk=device).count() == 1


def test_same_executor_and_old_client_heartbeats_do_not_close_live_terminal(remote):
    client, edge, device, _ = remote
    for executor in [None, "a" * 32]:
        heartbeat(edge, identity=observed(executor))
        sid = client.post(BASE, {"action": "open", "device_id": device}, format="json").data["id"]
        heartbeat(edge, identity=observed(executor))
        assert RemoteTerminal.objects.get(pk=sid).status == "open"
        client.post(BASE + "sessions/" + sid + "/", {"action": "close"}, format="json")


def test_executor_restart_stops_old_run_and_expires_its_pending_command(remote):
    from datetime import timedelta
    from django.utils import timezone
    from plane.quality.models import Defect
    from plane.quality.remote_models import RemoteAgentRun, RemoteCommand
    from plane.quality.remote_diagnostics import identity_key

    _, edge, device, project = remote
    heartbeat(edge, identity=observed("a" * 32))
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title="restart fixture", created_by=station.agent.owner)
    run = RemoteAgentRun.objects.create(
        workstation=station,
        defect=defect,
        owner=station.agent.owner,
        status="running",
        identity_key=identity_key(station),
        expires_at=timezone.now() + timedelta(minutes=2),
    )
    command = RemoteCommand.objects.create(
        workstation=station,
        run=run,
        payload={"kind": "patch_file", "path": "config.json"},
        expires_at=run.expires_at,
    )
    assert heartbeat(edge, identity=observed("b" * 32)).status_code == 200
    run.refresh_from_db()
    command.refresh_from_db()
    assert run.status == "failed"
    assert command.status == "expired" and command.payload == {}
    assert RemoteWorkstation.objects.filter(pk=device).count() == 1
