from uuid import uuid4
import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, DiagnosticJob
from plane.quality.diagnostic_retry import schedule_retry

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def retry_job(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="重试", identifier="RETRY")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    d = Defect.objects.create(project=p, created_by=create_user, title="失败后重试")
    return DiagnosticJob.objects.create(
        project=p,
        defect=d,
        created_by=create_user,
        request_id=uuid4(),
        mode="auto",
        status="completed",
        result={"model_status": "failed", "model_error_code": "AGENT_FAILED", "findings": [{"kind": "error"}]},
    )


def test_failed_retry_is_delayed_bounded_and_preserves_rules(retry_job, mocker, django_capture_on_commit_callbacks):
    send = mocker.patch("plane.quality.tasks.run_diagnostic.apply_async")
    with django_capture_on_commit_callbacks(execute=True):
        assert schedule_retry(retry_job)
    assert retry_job.status == "queued" and retry_job.result["findings"] == [{"kind": "error"}]
    assert send.call_args.kwargs["queue"] == "diagnostics" and send.call_args.kwargs["countdown"] == 30
    retry_job.status = "completed"
    with django_capture_on_commit_callbacks(execute=True):
        assert schedule_retry(retry_job)
    assert send.call_args.kwargs["countdown"] == 90
    retry_job.status = "completed"
    with django_capture_on_commit_callbacks(execute=True):
        assert schedule_retry(retry_job)
    assert send.call_args.kwargs["countdown"] == 270
    retry_job.status = "completed"
    assert not schedule_retry(retry_job)
    assert send.call_count == 3


def test_cancel_or_auth_error_never_retries(retry_job, mocker):
    send = mocker.patch("plane.quality.tasks.run_diagnostic.apply_async")
    retry_job.status = "cancelled"
    assert not schedule_retry(retry_job)
    retry_job.status = "completed"
    retry_job.result["model_error_code"] = "AGENT_PROVIDER_AUTH"
    assert not schedule_retry(retry_job)
    send.assert_not_called()


def test_manual_rediagnose_cancels_waiting_automatic_retry(session_client, retry_job, mocker):
    retry_job.status = "queued"
    retry_job.result["retry"] = {"count": 1, "limit": 2}
    retry_job.save()
    mocker.patch("plane.quality.diagnostics.enqueue")
    base = f"/api/workspaces/{retry_job.project.workspace.slug}/projects/{retry_job.project_id}/quality/"
    response = session_client.post(
        base + f"defects/{retry_job.defect_id}/diagnostics/",
        {"request_id": str(uuid4()), "mode": "rules"},
        format="json",
    )
    assert response.status_code == 201, response.content
    retry_job.refresh_from_db()
    assert retry_job.status == "cancelled"
    assert DiagnosticJob.objects.filter(defect=retry_job.defect, status="queued").count() == 1
