"""Saved filters stay private and cannot add arbitrary navigation or query expressions."""

import pytest
from plane.db.models import Project, ProjectMember, WorkspaceMember, User

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def saved_views(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="保存视图", identifier="SV")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/", project


def test_saved_filters_are_private_reusable_and_reject_navigation_fields(session_client, saved_views, workspace):
    base, project = saved_views
    created = session_client.post(
        base + "saved-views/",
        {
            "name": "我的待回归",
            "resource": "defects",
            "filters": {"view": "assigned_to_me", "status": "resolved", "severity": "major"},
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    own = session_client.get(base + "saved-views/?resource=defects")
    assert own.status_code == 200 and len(own.data) == 1
    assert own.data[0]["filters"]["status"] == "resolved"
    assert (
        session_client.post(
            base + "saved-views/",
            {
                "name": "恶意地址",
                "resource": "defects",
                "filters": {"url": "https://external.invalid", "project_id": "other"},
            },
            format="json",
        ).status_code
        == 400
    )
    other = User.objects.create(email="other-views@local.test", username="other-views")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    session_client.force_authenticate(user=other)
    assert session_client.get(base + "saved-views/?resource=defects").data == []
    assert session_client.delete(base + f"saved-views/{created.data['id']}/").status_code == 404


def test_guest_can_save_personal_filters_without_gaining_business_write(session_client, saved_views, create_user):
    base, project = saved_views
    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    response = session_client.post(
        base + "saved-views/", {"name": "只读查询", "resource": "defects", "filters": {"status": "open"}}, format="json"
    )
    assert response.status_code == 201, response.content
    assert session_client.post(base + "defects/", {"title": "不应获得写入权"}, format="json").status_code == 403
