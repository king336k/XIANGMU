"""Background diagnostics are cancellable and never claim a model result when not configured."""

from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def diagnostics(session_client, workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="后台诊断", identifier="DIAG")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{p.id}/quality/"
    d = session_client.post(
        base + "defects/",
        {"title": "连接失败", "description": "记录包含 timeout 及 connection refused 错误"},
        format="json",
    ).data
    return base, p, d


def test_rule_diagnostic_keeps_provenance_and_retry_request_is_idempotent(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    request = {"request_id": str(uuid4()), "mode": "rules"}
    created = session_client.post(base + f"defects/{d['id']}/diagnostics/", request, format="json")
    assert created.status_code == 201, created.content
    repeated = session_client.post(base + f"defects/{d['id']}/diagnostics/", request, format="json")
    assert repeated.status_code == 200 and repeated.data["id"] == created.data["id"]
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(created.data["id"])
    result = session_client.get(base + f"diagnostics/{created.data['id']}/")
    assert result.status_code == 200 and result.data["status"] == "completed", result.content
    assert result.data["result"]["method"] == "rules" and "模型" in result.data["result"]["notice"]
    assert result.data["result"]["findings"]


def test_cancelled_task_never_gets_completed_by_late_worker(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    created = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "rules"}, format="json"
    ).data
    cancel = session_client.post(base + f"diagnostics/{created['id']}/", {"action": "cancel"}, format="json")
    assert cancel.status_code == 200 and cancel.data["status"] == "cancelled"
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(created["id"])
    assert session_client.get(base + f"diagnostics/{created['id']}/").data["status"] == "cancelled"


def test_llm_mode_without_config_stays_explicitly_unconfigured(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.knowledge.assistant.provider_config", return_value={"configured": False})
    created = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "llm"}, format="json"
    )
    assert created.status_code == 201 and created.data["status"] == "unconfigured", created.content
    assert created.data["result"] == {}


def test_background_task_rechecks_revoked_project_access(session_client, diagnostics, mocker, create_user):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    job = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "rules"}, format="json"
    ).data
    ProjectMember.objects.filter(project=p, member=create_user).update(is_active=False)
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(job["id"])
    from plane.quality.models import DiagnosticJob

    row = DiagnosticJob.objects.get(pk=job["id"])
    assert row.status == "failed" and row.error_code == "ACCESS_REVOKED"


def test_private_key_block_is_not_retained_in_diagnostic_sample():
    from plane.quality.tasks import redact

    value = redact("error\n-----BEGIN PRIVATE KEY-----\nsecret-body-data\n-----END PRIVATE KEY-----\ntimeout")
    assert "secret-body-data" not in value and "timeout" in value


def test_cancellation_during_worker_does_not_get_overwritten_by_completed_result(session_client, diagnostics, mocker):
    base, p, d = diagnostics
    mocker.patch("plane.quality.diagnostics.enqueue")
    job = session_client.post(
        base + f"defects/{d['id']}/diagnostics/", {"request_id": str(uuid4()), "mode": "rules"}, format="json"
    ).data
    from plane.quality.models import DiagnosticJob

    def cancelled_midflight(current):
        DiagnosticJob.objects.filter(pk=current.id).update(status="cancelled")
        return "timeout", [], []

    mocker.patch("plane.quality.tasks.inspect", side_effect=cancelled_midflight)
    from plane.quality.tasks import run_diagnostic

    run_diagnostic(job["id"])
    assert DiagnosticJob.objects.get(pk=job["id"]).status == "cancelled"
