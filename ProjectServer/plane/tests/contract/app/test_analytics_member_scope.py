import pytest
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember, User, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_selected_project_counts_members_in_that_project_only(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Analytics", identifier="ANL")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    other = User.objects.create(username="analytics-other", email="analytics-other@example.test")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    browser = APIClient()
    browser.force_authenticate(create_user)
    response = browser.get(
        f"/api/workspaces/{workspace.slug}/advance-analytics-charts/",
        {"type": "projects", "project_ids": str(project.id)},
    )
    assert response.status_code == 200
    assert next(row["count"] for row in response.data if row["key"] == "members") == 1


def test_unjoined_project_cannot_leak_member_count(workspace, create_user):
    hidden = Project.objects.create(workspace=workspace, name="Hidden", identifier="HDN")
    other = User.objects.create(username="analytics-hidden", email="analytics-hidden@example.test")
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=hidden, member=other, role=20)
    browser = APIClient()
    browser.force_authenticate(create_user)
    response = browser.get(
        f"/api/workspaces/{workspace.slug}/advance-analytics/", {"tab": "overview", "project_ids": str(hidden.id)}
    )
    assert response.status_code == 200
    assert response.data["total_users"]["count"] == 0


def test_active_project_stats_exclude_unjoined_projects(workspace, create_user):
    hidden = Project.objects.create(workspace=workspace, name="Hidden stats", identifier="HDS")
    browser = APIClient()
    browser.force_authenticate(create_user)
    response = browser.get(f"/api/workspaces/{workspace.slug}/project-stats/", {"project_ids": str(hidden.id)})
    assert response.status_code == 200
    assert list(response.data) == []
