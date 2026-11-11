"""Automatic DAQ diagnostics retain immutable input versions and bounded ZIP evidence."""

import hashlib
import io
from uuid import uuid4
import zipfile
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember, Issue
from plane.quality.models import DiagnosticJob

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def source(session_client, workspace, create_user, mocker, settings, tmp_path):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    mocker.patch("plane.quality.diagnostics.enqueue")
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": False})
    project = Project.objects.create(workspace=workspace, name="自动初诊", identifier="AUTO")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    issue = Issue.objects.create(project=project, workspace=workspace, name="采集任务")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    response = session_client.post(
        base + "daq/bindings/",
        {
            "source_instance": "daq",
            "platform_task_id": 18,
            "source_record_id": "session-auto",
            "issue_id": str(issue.id),
        },
        format="json",
    )
    assert response.status_code == 201
    return base, project


def submit(client, base, key):
    return client.post(
        base + "daq/reports/",
        {
            "sourceRecordId": "session-auto",
            "platformTaskId": 18,
            "category": "Other",
            "title": "采集停止",
            "description": "请检查本次录制",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_daq_report_automatically_queues_once_without_assigning_technician(session_client, source):
    base, project = source
    key = str(uuid4())
    response = submit(session_client, base, key)
    assert response.status_code == 201
    defect = response.data["issueId"]
    jobs = DiagnosticJob.objects.filter(defect_id=defect)
    assert jobs.count() == 1
    assert jobs.first().mode == "auto"
    assert jobs.first().result["trigger"] == "daq_report"
    submit(session_client, base, key)
    assert jobs.count() == 1
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(jobs.first().id)
    job = jobs.get()
    assert job.status == "completed"
    assert job.result["method"] == "rules"
    assert job.result["model_status"] == "awaiting_materials"


def test_verified_zip_creates_new_report_and_diagnostics_read_inside_archive(session_client, source):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("logs/recording.log", "ERROR connection refused\nrequest timeout\n")
        bundle.writestr("private.txt", "-----BEGIN PRIVATE KEY-----\nsecret-value\n-----END PRIVATE KEY-----")
    raw = archive.getvalue()
    package = session_client.post(
        base + "packages/",
        {
            "name": "DAQ材料",
            "defect_id": defect,
            "source_system": "ENGRAM_DAQ",
            "external_id": "zip-1",
            "files": [{"path": "diagnostics.zip", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
        },
        format="json",
    ).data
    assert DiagnosticJob.objects.filter(defect_id=defect).count() == 1
    url = base + f"packages/{package['id']}/files/"
    response = session_client.post(url, {"file": SimpleUploadedFile("diagnostics.zip", raw)}, format="multipart")
    assert response.status_code == 201, response.content
    jobs = DiagnosticJob.objects.filter(defect_id=defect).order_by("created_at")
    assert jobs.count() == 2
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(jobs.last().id)
    result = jobs.last().result
    assert result["findings"]
    assert any(row.get("archive_entry") == "logs/recording.log" for row in result["sources"])
    assert "secret-value" not in str(result)
    assert result["version"] == 2
    log_source = next(row for row in result["sources"] if row.get("archive_entry") == "logs/recording.log")
    assert log_source["file_bytes"] == log_source["read_bytes"]
    assert log_source["preview_truncated"] is False
    session_client.post(url, {"file": SimpleUploadedFile("diagnostics.zip", raw)}, format="multipart")
    assert jobs.count() == 2
    run_diagnostic(jobs.first().id)
    assert jobs.first().result["sources"] == [], "Earlier report must not consume later-uploaded files."


def test_model_timeout_retains_rule_evidence_and_has_explicit_status(session_client, source, mocker):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=TimeoutError)
    from plane.quality.tasks import run_diagnostic

    job = DiagnosticJob.objects.get(defect_id=defect)
    job.result["trigger"] = "manual"
    job.save()
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "completed"
    assert job.result["model_status"] == "timeout"
    assert job.result["method"] == "rules"
    assert job.result["sources"] == []


def test_automatic_job_runs_for_reporter_and_rechecks_revocation(session_client, source, create_user, mocker):
    base, project = source
    from plane.quality.models import BusinessRole, ProjectRolePolicy

    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="REPORTER")
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    from plane.quality.tasks import run_diagnostic

    job = DiagnosticJob.objects.get(defect_id=defect)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "completed"
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    job.status = "queued"
    job.save()
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED"


def test_queue_wait_expiry_is_explicit_and_late_worker_cannot_overwrite(session_client, source):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    from django.utils import timezone
    from datetime import timedelta
    from plane.quality.diagnostics import expire_stale
    from plane.quality.models import Defect

    job = DiagnosticJob.objects.get(defect_id=defect)
    DiagnosticJob.objects.filter(pk=job.pk).update(status="running", started_at=timezone.now() - timedelta(minutes=4))
    expire_stale(Defect.objects.get(pk=defect))
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "DIAGNOSTIC_TIMEOUT"


def test_new_material_report_does_not_expose_private_snapshot_in_api(session_client, source):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    data = session_client.get(base + f"defects/{defect}/diagnostics/").data
    rows = data["results"] if isinstance(data, dict) else data
    assert len(rows) == 1 and "input" not in rows[0]["result"]


def test_long_queue_wait_is_not_confused_with_running_timeout(session_client, source):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    from django.utils import timezone
    from datetime import timedelta
    from plane.quality.diagnostics import expire_stale
    from plane.quality.models import Defect

    job = DiagnosticJob.objects.get(defect_id=defect)
    DiagnosticJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=4))
    expire_stale(Defect.objects.get(pk=defect))
    job.refresh_from_db()
    assert job.status == "queued"


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


def test_unsafe_archive_entry_is_not_interpreted(session_client, source, settings):
    from pathlib import Path
    from plane.quality.models import ProblemPackage, PackageFile
    from plane.quality.diagnostic_materials import inspect

    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../../outside.log", "secret error")
    raw = archive.getvalue()
    Path(settings.QUALITY_ATTACHMENT_ROOT, "unsafe.bin").write_bytes(raw)
    package = ProblemPackage.objects.create(
        project=project, defect_id=defect, name="unsafe", source_system="test", external_id="unsafe"
    )
    file = PackageFile.objects.create(
        project=project,
        package=package,
        name="unsafe.zip",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        storage_key="unsafe.bin",
    )
    job = DiagnosticJob.objects.get(defect_id=defect)
    job.result["input"]["files"] = [str(file.id)]
    text, sources, findings = inspect(job)
    assert sources[0]["scan_incomplete"] is True and "secret error" not in text


def test_fifty_reports_queue_once_each_and_retries_do_not_create_more(session_client, source):
    base, project = source
    keys = [str(uuid4()) for _ in range(50)]
    ids = [submit(session_client, base, key).data["issueId"] for key in keys]
    assert len(set(ids)) == 50
    assert DiagnosticJob.objects.filter(project=project).count() == 50
    for key in keys:
        assert submit(session_client, base, key).status_code == 200
    assert DiagnosticJob.objects.filter(project=project).count() == 50


@pytest.mark.parametrize(
    "error,code",
    [
        (ValueError("INVALID_DIAGNOSTIC_CITATION"), "INVALID_DIAGNOSTIC_CITATION"),
        (TimeoutError("private provider response"), "MODEL_TIMEOUT"),
        (RuntimeError("private provider response"), "MODEL_FAILED"),
    ],
)
def test_model_failure_records_safe_reason_without_provider_content(session_client, source, mocker, error, code):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    mocker.patch("plane.quality.tasks.analyze_diagnostic", side_effect=error)
    from plane.quality.tasks import run_diagnostic

    job = DiagnosticJob.objects.get(defect_id=defect)
    job.result["trigger"] = "manual"
    job.save()
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_error_code"] == code
    assert job.status == "completed" and job.result["method"] == "rules"
    assert "private provider response" not in str(job.result)


def test_automatic_model_waits_for_uploaded_materials(session_client, source, mocker):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    model = mocker.patch("plane.quality.tasks.analyze_diagnostic")
    from plane.quality.tasks import run_diagnostic

    job = DiagnosticJob.objects.get(defect_id=defect)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_status"] == "awaiting_materials"
    model.assert_not_called()


def test_multiple_packages_start_full_diagnosis_only_when_all_files_are_verified(session_client, source):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    raw = b"ERROR connection refused"
    packages = []
    for index in range(2):
        response = session_client.post(
            base + "packages/",
            {
                "name": "现场日志",
                "defect_id": defect,
                "source_system": "ENGRAM_DAQ",
                "external_id": f"batch-{index}",
                "files": [{"path": "recording.log", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
            },
            format="json",
        )
        assert response.status_code == 201
        packages.append(response.data["id"])
    for index, pk in enumerate(packages):
        response = session_client.post(
            base + f"packages/{pk}/files/",
            {
                "file": SimpleUploadedFile("recording.log", raw),
            },
            format="multipart",
        )
        assert response.status_code == 201
        assert DiagnosticJob.objects.filter(defect_id=defect).count() == (1 if index == 0 else 2)
    job = DiagnosticJob.objects.filter(defect_id=defect).latest("created_at")
    assert len(job.result["input"]["files"]) == 2


def test_current_report_keeps_success_after_failed_retry_but_never_old_materials(session_client, source):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    first = DiagnosticJob.objects.get(defect_id=defect)
    first.status = "completed"
    first.result.update(model_status="completed", method="hybrid", answer="已观察到连接失败", citations=[])
    first.save()
    retry = DiagnosticJob.objects.create(
        project=project,
        defect_id=defect,
        request_id=uuid4(),
        mode="auto",
        result={"input": first.result["input"], "version": 2, "model_status": "failed"},
        status="completed",
    )
    response = session_client.get(base + f"defects/{defect}/diagnostics/")
    assert response.data["current_report"]["id"] == str(first.id)
    assert response.data["latest_attempt"]["id"] == str(retry.id)
    assert "input" not in response.data["current_report"]["result"]
    retry.result["input"] = {**retry.result["input"], "files": [str(uuid4())]}
    retry.save()
    response = session_client.get(base + f"defects/{defect}/diagnostics/")
    assert response.data["current_report"]["id"] == str(retry.id)


def test_timeout_argument_in_traceback_does_not_mean_timeout_occurred(session_client, source):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    job = DiagnosticJob.objects.get(defect_id=defect)
    job.result["input"]["description"] = (
        "socket.create_connection(address, timeout=1)\nConnectionRefusedError: Connection refused"
    )
    from plane.quality.diagnostic_materials import inspect

    _, _, findings = inspect(job)
    assert "timeout" not in {row["kind"] for row in findings}
    assert "connection" in {row["kind"] for row in findings}


def test_large_log_fault_reaches_model_after_upload_scan_and_summary(session_client, source, mocker):
    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    raw = (
        b"INFO recorder healthy\n" * 80000
        + b"ERROR connection refused target=127.0.0.1:65123\n"
        + b"INFO scheduler waiting\n" * 80000
    )
    package = session_client.post(
        base + "packages/",
        {
            "name": "large-log",
            "defect_id": defect,
            "source_system": "ENGRAM_DAQ",
            "external_id": "large-log",
            "files": [{"path": "complete.log", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}],
        },
        format="json",
    )
    assert package.status_code == 201, package.data
    uploaded = session_client.post(
        base + f"packages/{package.data['id']}/files/",
        {
            "file": SimpleUploadedFile("complete.log", raw),
        },
        format="multipart",
    )
    assert uploaded.status_code == 201, uploaded.data
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    model = mocker.patch(
        "plane.quality.tasks.analyze_diagnostic",
        return_value={
            "answer": "观察到连接被拒绝，仍需核对监听服务。",
            "citations": [],
            "suggested_actions": [],
            "verification_steps": [],
            "engine": "test-boundary",
        },
    )
    from plane.quality.tasks import run_diagnostic

    job = DiagnosticJob.objects.filter(defect_id=defect).latest("created_at")
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_status"] == "completed"
    assert "target=127.0.0.1:65123" in model.call_args.args[1]
    assert "target=127.0.0.1:65123" in model.call_args.args[2][0]["excerpt"]
    assert job.result["sources"][0]["scanned_bytes"] == len(raw)
    downloaded = session_client.get(base + f"files/{uploaded.data['id']}/download/")
    assert hashlib.sha256(b"".join(downloaded.streaming_content)).hexdigest() == hashlib.sha256(raw).hexdigest()


def test_manual_model_waits_for_all_registered_materials(session_client, source, mocker):
    from plane.quality.models import ProblemPackage
    from plane.quality.tasks import run_diagnostic

    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    ProblemPackage.objects.create(project=project, defect_id=defect, name="尚未传完",
                                  source_system="ENGRAM_DAQ", external_id="waiting")
    job = DiagnosticJob.objects.get(defect_id=defect)
    job.result["trigger"] = "manual"
    job.save()
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    model = mocker.patch("plane.quality.tasks.analyze_diagnostic")
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_status"] == "awaiting_materials"
    model.assert_not_called()


def test_incomplete_scanning_cannot_produce_a_model_diagnosis(session_client, source, mocker):
    from plane.quality.tasks import run_diagnostic

    base, project = source
    defect = submit(session_client, base, str(uuid4())).data["issueId"]
    job = DiagnosticJob.objects.get(defect_id=defect)
    job.result["trigger"] = "manual"
    job.save()
    mocker.patch("plane.quality.tasks.inspect", return_value=("ERROR connection refused", [
        {"file_id": str(uuid4()), "name": "incomplete.log", "read_bytes": 10, "scan_incomplete": True}], []))
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": True})
    model = mocker.patch("plane.quality.tasks.analyze_diagnostic")
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.result["model_status"] == "material_scan_incomplete"
    model.assert_not_called()
