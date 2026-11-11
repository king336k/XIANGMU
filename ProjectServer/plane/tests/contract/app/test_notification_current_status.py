import pytest
from rest_framework.test import APIClient
from plane.db.models import Notification, Project, ProjectMember
from plane.quality.models import Defect, TestPlan

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def notice_data(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Notice", identifier="NOTICE")
    membership = ProjectMember.objects.create(project=project, member=create_user, role=20)
    defect = Defect.objects.create(project=project, title="Current status", status="open")
    row = Notification.objects.create(
        workspace=workspace,
        project=project,
        receiver=create_user,
        sender="quality",
        title="旧通知：待处理",
        entity_name="quality",
        entity_identifier=defect.id,
        data={
            "quality": {
                "title": "旧通知：待处理",
                "url": f"/{workspace.slug}/projects/{project.id}/defects?defect={defect.id}",
            }
        },
    )
    client = APIClient()
    client.force_authenticate(create_user)
    return client, project, membership, defect, row


def test_notification_uses_current_defect_status_without_rewriting_historical_title(workspace, notice_data):
    client, project, membership, defect, row = notice_data
    Defect.objects.filter(pk=defect.pk).update(status="closed")
    response = client.get(f"/api/workspaces/{workspace.slug}/users/notifications/")
    assert response.status_code == 200
    notice = next(item for item in response.data if str(item["id"]) == str(row.id))
    assert notice["data"]["current_record"] == {
        "kind": "defect",
        "label": "已关闭",
        "status": "closed",
        "available": True,
    }
    assert notice["title"] == "旧通知：待处理"


def test_test_plan_notifications_include_current_plan_status(workspace, notice_data):
    client, project, membership, defect, row = notice_data
    plan = TestPlan.objects.create(project=project, name="Plan", status="completed")
    row.entity_identifier = plan.id
    row.data = {
        "quality": {
            "url": f"/{workspace.slug}/projects/{project.id}/quality?tab=plans&plan={plan.id}",
            "title": "等待确认",
        }
    }
    row.save()
    response = client.get(f"/api/workspaces/{workspace.slug}/users/notifications/")
    record = response.data[0]["data"]["current_record"]
    assert record["kind"] == "plan" and record["label"] == "测试结果已确认"


def test_revoked_project_access_does_not_expose_current_business_status(workspace, notice_data):
    client, project, membership, defect, row = notice_data
    membership.is_active = False
    membership.save()
    response = client.get(f"/api/workspaces/{workspace.slug}/users/notifications/")
    assert response.status_code == 200
    assert response.data == []


def test_reading_one_notification_preserves_business_state_and_other_unread(workspace, notice_data):
    client, project, membership, defect, row = notice_data
    other = Notification.objects.create(
        workspace=workspace,
        project=project,
        receiver=row.receiver,
        sender="quality",
        title="Other",
        entity_name="quality",
        entity_identifier=defect.id,
        data=row.data,
    )
    response = client.post(f"/api/workspaces/{workspace.slug}/users/notifications/{row.id}/read/")
    assert response.status_code == 200
    assert response.data["data"]["current_record"]["status"] == "open"
    row.refresh_from_db()
    other.refresh_from_db()
    defect.refresh_from_db()
    assert row.read_at is not None and other.read_at is None
    assert defect.status == "open"


def test_version_task_notification_has_current_task_state(workspace, notice_data):
    from plane.db.models import Issue, State

    client, project, membership, defect, row = notice_data
    state = State.objects.create(project=project, name="In Progress", group="started")
    issue = Issue.objects.create(project=project, name="Task", state=state)
    row.entity_identifier = issue.id
    row.data = {"quality": {"url": f"/{workspace.slug}/projects/{project.id}/issues/{issue.id}/"}}
    row.save()
    response = client.get(f"/api/workspaces/{workspace.slug}/users/notifications/")
    assert response.data[0]["data"]["current_record"]["label"] == "进行中"


def test_status_enrichment_uses_constant_queries_for_many_notices(
    workspace, notice_data, django_assert_max_num_queries
):
    from plane.quality.notifications import serialize_with_current_status
    from types import SimpleNamespace

    client, project, membership, defect, row = notice_data
    rows = list(Notification.objects.filter(id=row.id).select_related("triggered_by"))
    with django_assert_max_num_queries(5):
        result = serialize_with_current_status(rows * 50, SimpleNamespace(user=row.receiver))
    assert len(result) == 50
    assert all(item["data"]["current_record"]["status"] == "open" for item in result)
