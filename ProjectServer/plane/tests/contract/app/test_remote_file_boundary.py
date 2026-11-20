"""File operations share one application boundary and retain identity guards."""
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from plane.db.models import ProjectMember
from plane.quality.errors import Conflict
from plane.quality.remote_access import identity_key
from plane.quality.remote_file_operations import create_file_request, read_file_request
from plane.quality.remote_models import RemoteFileRequest, RemoteUploadedFile, RemoteWorkstation
from plane.tests.contract.app.test_remote_diagnostics import BASE, heartbeat

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db(transaction=True)]


def test_file_application_imports_without_http_view_modules():
    script = "import django,sys; django.setup(); "
    script += "sys.modules['plane.quality.remote_files']=None; sys.modules['plane.quality.remote_diagnostics']=None; sys.modules['plane.quality.views']=None; "
    script += "from plane.quality.remote_file_operations import create_file_request,read_file_request,record_upload_result; "
    script += "assert all(callable(value) for value in [create_file_request,read_file_request,record_upload_result])"
    result = subprocess.run([sys.executable, "-c", script], env=os.environ.copy(),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_file_http_adapter_calls_the_application_service(remote):
    client, _, device, _ = remote
    with patch("plane.quality.remote_files.create_file_request", return_value={"id": "synthetic", "status": "pending"}) as create:
        response = client.post(BASE + "files/", {"device_id": device, "action": "list", "target": "operator"}, format="json")
    assert response.status_code == 201
    assert response.data == {"id": "synthetic", "status": "pending"}
    assert create.call_count == 1
    assert create.call_args.args[1]["device_id"] == device
    with patch("plane.quality.remote_files.read_file_request", return_value={"status": "done"}) as read:
        response = client.get(BASE + "files/" + device + "/")
    assert response.status_code == 200 and response.data == {"status": "done"}
    assert str(read.call_args.args[1]) == device


def test_direct_file_request_preserves_owner_result_and_revocation(remote):
    _, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.select_related("agent__owner").get(pk=device)
    owner = station.agent.owner
    value = create_file_request(owner, {"device_id": device, "action": "list", "target": "operator", "path": ""})
    job = RemoteFileRequest.objects.get(pk=value["id"])
    assert job.identity_key == identity_key(station)
    assert job.command.payload == {"kind": "file_browser", "request": {"action": "list", "target": "operator", "offset": 0, "path": ""}}
    job.command.status = "done"
    job.command.result = {"ok": True, "file_result": {"entries": [{"name": "a.bin", "kind": "file"}]}}
    job.command.save(update_fields=["status", "result"])
    assert read_file_request(owner, job.id)["result"]["entries"][0]["name"] == "a.bin"
    ProjectMember.objects.filter(project=project, member=owner).update(is_active=False)
    with pytest.raises(PermissionDenied):
        read_file_request(owner, job.id)


def test_direct_file_request_rejects_new_device_identity_and_expired_result(remote):
    _, edge, device, _ = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.select_related("agent__owner").get(pk=device)
    owner = station.agent.owner
    value = create_file_request(owner, {"device_id": device, "action": "list", "target": "robot"})
    job = RemoteFileRequest.objects.get(pk=value["id"])
    station.boot_id = "changed"
    station.save(update_fields=["boot_id"])
    with pytest.raises(Conflict):
        read_file_request(owner, job.id)
    station.boot_id = "boot1"
    station.save(update_fields=["boot_id"])
    job.command.expires_at = timezone.now()
    job.command.save(update_fields=["expires_at"])
    with pytest.raises(Conflict):
        read_file_request(owner, job.id)


def test_direct_invalid_upload_rolls_back_and_ticket_keeps_target_binding(remote):
    _, edge, device, _ = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.select_related("agent__owner").get(pk=device)
    owner = station.agent.owner
    with pytest.raises(ValidationError):
        create_file_request(owner, {"device_id": device, "action": "upload_start", "target": "operator", "filename": "x.zip", "size": 0, "sha256": "invalid"})
    assert not station.commands.exists()
    assert not RemoteUploadedFile.objects.filter(workstation=station).exists()
    value = create_file_request(owner, {"device_id": device, "action": "upload_start", "target": "robot", "filename": "x.zip", "size": 0, "sha256": "a" * 64})
    job = RemoteFileRequest.objects.get(pk=value["id"])
    from plane.quality.remote_file_operations import record_upload_result
    job.command.result = {"ok": True, "file_result": {"ticket": "b" * 32}}
    record_upload_result(job.command)
    with pytest.raises(Http404):
        create_file_request(owner, {"device_id": device, "action": "upload_chunk", "target": "operator", "ticket": "b" * 32, "offset": 0, "data": "YQ=="})
