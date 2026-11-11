"""A native defect diagnoses relevant attachments; no attachment is not a required step."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from plane.db.models import Project, ProjectMember
from plane.quality.models import DiagnosticJob

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def native(session_client, workspace, create_user, settings, tmp_path, mocker):
    settings.QUALITY_ATTACHMENT_ROOT = str(tmp_path)
    mocker.patch("plane.quality.diagnostics.enqueue")
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": False})
    project = Project.objects.create(workspace=workspace, name="平台附件诊断", identifier="NATIVEDIAG")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    defect = session_client.post(base + "defects/", {"title": "本地服务启动失败"}, format="json").data
    return base, project, defect


def test_native_log_upload_automatically_diagnoses_once_and_keeps_origin(session_client, native):
    from plane.quality.tasks import run_diagnostic

    base, project, defect = native
    assert not DiagnosticJob.objects.filter(defect_id=defect["id"]).exists()
    path = base + f"defects/{defect['id']}/attachments/"
    raw = b"ERROR ConnectionRefusedError errno111 target=127.0.0.1:5001\n"
    response = session_client.post(path, {"file": SimpleUploadedFile("service.log", raw)}, format="multipart")
    assert response.status_code == 201, response.content
    jobs = DiagnosticJob.objects.filter(defect_id=defect["id"])
    assert jobs.count() == 1
    run_diagnostic(jobs.get().id)
    job = jobs.get()
    assert job.status == "completed" and job.result["sources"]
    assert job.result["model_status"] == "unconfigured"
    session_client.post(path, {"file": SimpleUploadedFile("service.log", raw)}, format="multipart")
    assert jobs.count() == 1
    current = session_client.get(base + f"defects/{defect['id']}/").data
    assert current["source_kind"] == "manual" and current["requires_data_regression"] is False


def test_non_diagnostic_binary_attachment_does_not_trigger_model(session_client, native):
    base, project, defect = native
    r = session_client.post(
        base + f"defects/{defect['id']}/attachments/",
        {"file": SimpleUploadedFile("capture.bin", b"\x00\x01opaque")},
        format="multipart",
    )
    assert r.status_code == 201 and not DiagnosticJob.objects.filter(defect_id=defect["id"]).exists()


def test_revoked_native_uploader_does_not_publish_diagnosis(session_client, native, create_user):
    from plane.quality.tasks import run_diagnostic

    base, project, defect = native
    session_client.post(
        base + f"defects/{defect['id']}/attachments/",
        {"file": SimpleUploadedFile("service.log", b"ERROR local service failed")},
        format="multipart",
    )
    job = DiagnosticJob.objects.get(defect_id=defect["id"])
    ProjectMember.objects.filter(project=project, member=create_user).update(is_active=False)
    run_diagnostic(job.id)
    job.refresh_from_db()
    assert job.status == "failed" and job.error_code == "ACCESS_REVOKED"
