"""Onsite analysis receives the verified original report, not only its title."""
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone

from plane.quality.models import Defect, PackageFile, ProblemPackage
from plane.quality.remote_diagnostics import identity_key
from plane.quality.remote_models import RemoteAgentRun, RemoteWorkstation
from plane.tests.contract.app.test_remote_diagnostics import heartbeat

pytest_plugins = ["plane.tests.contract.app.test_remote_diagnostics"]
pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def add_file(project, defect, root, body, *, status="files_verified", digest=None):
    package = ProblemPackage.objects.create(project=project, defect=defect, name="report",
        source_system="ENGRAM_TELEOP_DAQ", external_id=uuid4().hex, status=status, files=[])
    data = body.encode()
    file = PackageFile.objects.create(project=project, package=package, name="feedback.json",
        size=len(data), sha256=digest or hashlib.sha256(data).hexdigest(), storage_key=uuid4().hex)
    (root / file.storage_key).write_bytes(data)
    return file


def create_run(remote):
    _, edge, device, project = remote
    heartbeat(edge)
    station = RemoteWorkstation.objects.get(pk=device)
    defect = Defect.objects.create(project=project, title="reset failed", description="reported failure")
    return project, defect, RemoteAgentRun.objects.create(workstation=station, defect=defect,
        owner=station.agent.owner, identity_key=identity_key(station),
        expires_at=timezone.now() + timedelta(minutes=5))


def test_uploaded_producer_error_reaches_actual_runner_input(remote, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project, defect, run = create_run(remote)
    marker = "reset goal is invalid: joint limit violation"
    body = json.dumps({"sourceSystem": "ENGRAM_TELEOP_DAQ", "evidence": {"observations": {
        "teleop": {"source": "/api/launcher/feedback-context", "capturedAt": "2026-11-19T12:45:30Z",
            "data": {"observations": {"nodes": {"data": {"processes": [
                {"name": "solver", "lines": ["2026-11-19 20:44:14 ERROR " + marker]}
            ]}}}}}}}})
    file = add_file(project, defect, tmp_path, body)
    from plane.quality.remote_tasks import remote_repair
    result = {"summary": "limited inspection", "repaired": False}
    with patch("plane.quality.remote_tasks.provider_config", return_value={"configured": True}), \
         patch("plane.quality.remote_tasks.subprocess.run", return_value=SimpleNamespace(
             returncode=0, stdout=json.dumps(result))) as execute:
        remote_repair.run(str(run.id))
    context = json.loads(execute.call_args.kwargs["input"])["context"]
    evidence = context["feedback_materials"]
    assert marker in json.dumps(evidence)
    assert str(file.id) in json.dumps(evidence)
    assert file.sha256 in json.dumps(evidence)
    assert evidence["observation_scope"] == "uploaded_historical_evidence"
    assert context["repair_allowed"] is False


def test_configuration_target_is_derived_from_verified_feedback_not_model_input(remote, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project, defect, run = create_run(remote)
    body = json.dumps({'sourceSystem':'ENGRAM_TELEOP_DAQ','evidence':{'observations':{
        'runtimeConfig':{'status':'available','data':{'robot':'profile-a','password':'never-return'}}}}})
    add_file(project, defect, tmp_path, body)
    from plane.quality.remote_materials import feedback_configuration_target
    assert feedback_configuration_target(run) == 'profile-a'
    add_file(project, defect, tmp_path, body.replace('profile-a','profile-b'))
    assert feedback_configuration_target(run) is None


def test_configuration_target_rejects_paths_bad_hash_and_unknown_source(remote, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project, defect, run = create_run(remote)
    body = json.dumps({'sourceSystem':'ENGRAM_TELEOP_DAQ','evidence':{'observations':{
        'runtimeConfig':{'status':'available','data':{'robot':'../secret'}}}}})
    add_file(project, defect, tmp_path, body)
    from plane.quality.remote_materials import feedback_configuration_target
    assert feedback_configuration_target(run) is None


def test_materials_are_defect_project_verified_and_snapshot_scoped(remote, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project, defect, run = create_run(remote)
    good = add_file(project, defect, tmp_path, "ERROR correct report")
    future = add_file(project, defect, tmp_path, "ERROR FUTURE_REPORT")
    PackageFile.objects.filter(pk=future.pk).update(created_at=timezone.now() + timedelta(minutes=1))
    other = Defect.objects.create(project=project, title="another computer")
    add_file(project, other, tmp_path, "ERROR OTHER_DEFECT")
    add_file(project, defect, tmp_path, "ERROR UNVERIFIED_PACKAGE", status="pending")
    from plane.quality.remote_materials import feedback_materials
    material = feedback_materials(run)
    assert "correct report" in json.dumps(material)
    assert str(good.id) in json.dumps(material)
    assert all(value not in json.dumps(material) for value in
               ("FUTURE_REPORT", "OTHER_DEFECT", "UNVERIFIED_PACKAGE"))


def test_invalid_hash_is_reported_without_trusting_content(remote, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    project, defect, run = create_run(remote)
    add_file(project, defect, tmp_path, "ERROR TAMPERED_CONTENT", digest="0" * 64)
    from plane.quality.remote_materials import feedback_materials
    material = feedback_materials(run)
    assert material["status"] == "incomplete"
    assert "TAMPERED_CONTENT" not in json.dumps(material)
    assert material["material_coverage"][0]["verified"] is False
