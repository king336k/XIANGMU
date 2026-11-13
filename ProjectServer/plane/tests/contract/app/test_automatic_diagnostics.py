"""Current signed DAQ reports automatically diagnose verified materials without external identities."""

import hashlib
import io
import json
import zipfile
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.quality.models import DiagnosticJob, Defect, ProblemPackage
from plane.tests.contract.app.test_daq_reporting import reporting, call, upload_part, revoke_grants

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def current(reporting, settings, tmp_path, mocker):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": False})
    return reporting


def submit(current, event=None):
    project, user, payload, state = current
    response = call(
        "/api/quality-auth/daq-reports/",
        {**payload, "hubProjectId": str(project.id), "eventId": event or str(uuid4())},
        "POST",
    )
    assert response.status_code in {200, 201}, response.content
    return response


def package(report_id, raw, name="recording.log"):
    response = call(
        f"/api/quality-auth/daq-reports/{report_id}/packages/",
        {
            "name": "现场材料",
            "defect_id": report_id,
            "source_system": "ENGRAM_DAQ",
            "external_id": str(uuid4()),
            "files": [{"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
        },
        "POST",
    )
    assert response.status_code == 201, response.content
    return response.data["id"]


def upload(report_id, package_id, raw, name="recording.log"):
    response = upload_part(
        f"/api/quality-auth/daq-reports/{report_id}/packages/{package_id}/files/",
        {"file": SimpleUploadedFile(name, raw)},
    )
    assert response.status_code in {200, 201}, response.content
    return response


def material(current, raw=b"ERROR connection refused", name="recording.log"):
    report_id = submit(current).data["issueId"]
    package_id = package(report_id, raw, name)
    upload(report_id, package_id, raw, name)
    return report_id, DiagnosticJob.objects.get(defect_id=report_id)


def run(job):
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(job.id)
    job.refresh_from_db()
    return job


def test_signed_report_waits_for_materials_and_retry_does_not_create_duplicate(current):
    event = str(uuid4())
    first = submit(current, event)
    second = submit(current, event)
    assert first.status_code == 201 and second.status_code == 200
    assert first.data["issueId"] == second.data["issueId"]
    assert first.data["diagnosticStatus"] == "waiting_materials"
    assert not DiagnosticJob.objects.exists()


def test_verified_materials_queue_once_and_repeated_upload_does_not_repeat(current):
    raw = b"ERROR connection refused"
    report_id = submit(current).data["issueId"]
    pk = package(report_id, raw)
    upload(report_id, pk, raw)
    assert DiagnosticJob.objects.filter(defect_id=report_id).count() == 1
    upload(report_id, pk, raw)
    assert DiagnosticJob.objects.filter(defect_id=report_id).count() == 1
    job = run(DiagnosticJob.objects.get(defect_id=report_id))
    assert job.status == "completed" and job.result["method"] == "rules"
    assert job.result["sources"]


def test_all_packages_must_be_verified_before_automatic_diagnosis(current):
    report_id = submit(current).data["issueId"]
    raw = b"ERROR timeout"
    one, two = package(report_id, raw), package(report_id, raw)
    upload(report_id, one, raw)
    assert not DiagnosticJob.objects.filter(defect_id=report_id).exists()
    upload(report_id, two, raw)
    job = DiagnosticJob.objects.get(defect_id=report_id)
    assert len(job.result["input"]["files"]) == 2


def test_zip_diagnostic_reads_log_and_redacts_sensitive_file(current):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("logs/recording.log", "ERROR connection refused\nrequest timeout\n")
        bundle.writestr("private.txt", "-----BEGIN PRIVATE KEY-----\nsecret-value\n-----END PRIVATE KEY-----")
    report_id, job = material(current, archive.getvalue(), "diagnostics.zip")
    job = run(job)
    assert job.status == "completed"
    assert any(row.get("archive_entry") == "logs/recording.log" for row in job.result["sources"])
    assert "secret-value" not in json.dumps(job.result)
    assert any(
        row.get("archive_entry") == "private.txt" and "secret-value" not in row.get("excerpt", "")
        for row in job.result["sources"]
    )


def test_revoked_daq_project_cannot_run_queued_diagnostic(current, mocker):
    _, job = material(current)
    revoke_grants(current[3])
    inspect = mocker.patch("plane.quality.tasks.inspect")
    job = run(job)
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED"
    inspect.assert_not_called()


@pytest.mark.parametrize(
    "error,code",
    [
        (TimeoutError("private provider response"), "MODEL_TIMEOUT"),
        (RuntimeError("private provider response"), "MODEL_FAILED"),
        (ValueError("INVALID_DIAGNOSTIC_CITATION"), "INVALID_DIAGNOSTIC_CITATION"),
    ],
)
def test_model_failure_keeps_rules_and_safe_error_only(current, mocker, error, code):
    _, job = material(current)
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=error)
    job = run(job)
    assert job.status == ("queued" if code == "MODEL_TIMEOUT" else "completed")
    assert job.result["method"] == "rules"
    assert job.result["model_error_code"] == code
    assert "private provider response" not in json.dumps(job.result)


def test_queue_and_running_deadlines_are_distinct(current):
    from datetime import timedelta
    from django.utils import timezone
    from plane.quality.diagnostics import expire_stale

    report_id, job = material(current)
    DiagnosticJob.objects.filter(pk=job.id).update(created_at=timezone.now() - timedelta(minutes=4))
    expire_stale(Defect.objects.get(pk=report_id))
    job.refresh_from_db()
    assert job.status == "queued"
    DiagnosticJob.objects.filter(pk=job.id).update(status="running", started_at=timezone.now() - timedelta(minutes=8))
    expire_stale(Defect.objects.get(pk=report_id))
    job = run(job)
    assert job.status == "failed" and job.error_code == "DIAGNOSTIC_TIMEOUT"


def test_large_verified_log_reaches_model_and_full_file_is_preserved(current, mocker):
    raw = (
        b"INFO recorder healthy\n" * 80000
        + b"ERROR connection refused target=127.0.0.1:65123\n"
        + b"INFO waiting\n" * 80000
    )
    report_id, job = material(current, raw, "complete.log")
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    model = mocker.patch(
        "plane.quality.tasks.analyze_diagnostic",
        return_value={"answer": "需要核对监听服务", "citations": [], "engine": "test-boundary"},
    )
    job = run(job)
    assert job.result["model_status"] == "completed"
    assert "127.0.0.1:65123" in model.call_args.args[1]
    assert job.result["sources"][0]["scanned_bytes"] == len(raw)
    from plane.quality.models import PackageFile

    file = PackageFile.objects.get(package__defect_id=report_id)
    response = call(f"/api/quality-auth/daq-reports/{report_id}/files/{file.id}/download/")
    assert (
        response.status_code == 200
        and hashlib.sha256(b"".join(response.streaming_content)).hexdigest() == hashlib.sha256(raw).hexdigest()
    )


def test_fifty_signed_reports_and_retries_do_not_duplicate(current):
    keys = [str(uuid4()) for _ in range(50)]
    ids = [submit(current, key).data["issueId"] for key in keys]
    assert len(set(ids)) == 50
    assert all(submit(current, key).status_code == 200 for key in keys)
    assert Defect.objects.count() == 50 and not DiagnosticJob.objects.exists()


def test_model_claim_with_unknown_evidence_is_rejected(mocker):
    from plane.quality.diagnostic_model import analyze_diagnostic
    from types import SimpleNamespace
    import json

    client = mocker.MagicMock()
    client.__enter__.return_value.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "answer": "已确认硬件损坏",
                            "suggested_actions": [],
                            "verification_steps": [],
                            "citations": ["FILE-other-project"],
                        }
                    )
                )
            )
        ]
    )
    mocker.patch("plane.quality.diagnostic_model.OpenAI", return_value=client)
    mocker.patch.dict("os.environ", {}, clear=True)
    with pytest.raises(ValueError, match="CITATION"):
        analyze_diagnostic(
            {"api_key": "synthetic", "base_url": "http://local.invalid", "model": "test"}, "连接失败", [], []
        )


def test_incomplete_scan_never_calls_model(current, mocker):
    _, job = material(current)
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    mocker.patch(
        "plane.quality.tasks.inspect", return_value=("ERROR timeout", [{"read_bytes": 10, "scan_incomplete": True}], [])
    )
    model = mocker.patch("plane.quality.tasks.analyze_diagnostic")
    job = run(job)
    assert job.result["model_status"] == "material_scan_incomplete"
    model.assert_not_called()


def test_timeout_parameter_in_traceback_is_not_a_timeout_fact(current):
    from plane.quality.diagnostic_materials import inspect

    _, job = material(
        current, b"socket.create_connection(address, timeout=1)\nConnectionRefusedError: Connection refused"
    )
    job.result["input"]["description"] = (
        "socket.create_connection(address, timeout=1)\nConnectionRefusedError: Connection refused"
    )
    _, _, findings = inspect(job)
    assert "timeout" not in {row["kind"] for row in findings}
    assert "connection" in {row["kind"] for row in findings}


def test_partial_upload_does_not_start_model_even_for_manual_retry(current, mocker, create_user, session_client):
    from plane.db.models import ProjectMember
    from plane.quality.tasks import run_diagnostic

    report_id, job = material(current)
    project = current[0]
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    ProblemPackage.objects.create(
        project=project, defect_id=report_id, name="pending", source_system="ENGRAM_DAQ", external_id="pending"
    )
    job.created_by = create_user
    job.result["trigger"] = "manual"
    job.save()
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    model = mocker.patch("plane.quality.tasks.analyze_diagnostic")
    job = run(job)
    assert job.result["model_status"] == "awaiting_materials"
    model.assert_not_called()


def test_current_success_is_retained_after_failed_retry_but_not_after_changed_material(
    current, session_client, create_user
):
    from plane.db.models import ProjectMember

    report_id, job = material(current)
    project = current[0]
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    job.status = "completed"
    job.result.update(model_status="completed", method="hybrid", answer="已观察到连接失败", citations=[])
    job.save()
    retry = DiagnosticJob.objects.create(
        project=project,
        defect_id=report_id,
        request_id=uuid4(),
        mode="auto",
        status="completed",
        result={"input": job.result["input"], "version": 2, "model_status": "failed"},
    )
    path = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/defects/{report_id}/diagnostics/"
    response = session_client.get(path)
    assert response.data["current_report"]["id"] == str(job.id)
    assert response.data["latest_attempt"]["id"] == str(retry.id)
    assert "input" not in response.data["current_report"]["result"]
    retry.result["input"] = {**retry.result["input"], "files": [str(uuid4())]}
    retry.save()
    assert session_client.get(path).data["current_report"]["id"] == str(retry.id)
