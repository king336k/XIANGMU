"""DAQ polling must expose expired worker and queue jobs as terminal failures."""

from datetime import timedelta
from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import Issue, Project, ProjectMember
from plane.quality.models import DiagnosticJob

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize(
    "status,age,error",
    [
        ("running", 200, "DIAGNOSTIC_TIMEOUT"),
        ("queued", 901, "QUEUE_WAIT_TIMEOUT"),
    ],
)
def test_daq_detail_expires_stale_jobs_without_native_dashboard_visit(
    session_client, workspace, create_user, mocker, status, age, error
):
    mocker.patch("plane.quality.diagnostics.enqueue")
    project = Project.objects.create(workspace=workspace, name="DAQ时限", identifier="DEADLINE")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    issue = Issue.objects.create(project=project, workspace=workspace, name="采集任务")
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    response = session_client.post(
        base + "daq/bindings/",
        {
            "source_instance": "daq",
            "platform_task_id": 18,
            "source_record_id": "deadline-session",
            "issue_id": str(issue.id),
        },
        format="json",
    )
    assert response.status_code == 201
    response = session_client.post(
        base + "daq/reports/",
        {
            "sourceRecordId": "deadline-session",
            "platformTaskId": 18,
            "category": "Other",
            "title": "连接失败",
            "description": "受控超时测试",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 201
    defect = response.data["issueId"]
    job = DiagnosticJob.objects.get(defect_id=defect)
    old = timezone.now() - timedelta(seconds=age)
    DiagnosticJob.objects.filter(pk=job.pk).update(
        status=status, started_at=old if status == "running" else None, created_at=old
    )
    response = session_client.get(base + f"daq/issues/{defect}/")
    assert response.status_code == 200
    latest = response.data["diagnostics"][0]
    assert latest["status"] == "failed"
    assert latest["error_code"] == error
    assert latest["completed_at"]
