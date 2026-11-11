"""Fixed navigation does not expand workspace or project authorization."""

from uuid import uuid4
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.mark.parametrize("workspace_role,expected", [(20, 200), (15, 200), (5, 403)])
def test_analytics_workspace_role_boundary(workspace, create_user, workspace_role, expected):
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=workspace_role)
    client = APIClient()
    client.force_authenticate(create_user)
    response = client.get(f"/api/workspaces/{workspace.slug}/advance-analytics/", {"tab": "overview"})
    assert response.status_code == expected


@pytest.mark.parametrize("action", ["post", "delete"])
def test_readonly_workspace_cannot_archive_or_restore_even_with_project_role(workspace, create_user, action):
    project = Project.objects.create(
        workspace=workspace,
        name="Read only",
        identifier="RO" + uuid4().hex[:5],
        archived_at=timezone.now() if action == "delete" else None,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
    client = APIClient()
    client.force_authenticate(create_user)
    response = getattr(client, action)(f"/api/workspaces/{workspace.slug}/projects/{project.id}/archive/")
    assert response.status_code == 403
    project.refresh_from_db()
    assert bool(project.archived_at) == (action == "delete")


@pytest.mark.parametrize("action", ["post", "delete"])
def test_workspace_admin_still_cannot_modify_unjoined_project(workspace, create_user, action):
    project = Project.objects.create(workspace=workspace, name="Unjoined", identifier="U" + uuid4().hex[:5])
    client = APIClient()
    client.force_authenticate(create_user)
    response = getattr(client, action)(f"/api/workspaces/{workspace.slug}/projects/{project.id}/archive/")
    assert response.status_code == 403


@pytest.mark.parametrize("workspace_role", [20, 15])
@pytest.mark.parametrize("action", ["post", "delete"])
def test_authorized_project_admin_can_archive_and_restore(workspace, create_user, workspace_role, action):
    project = Project.objects.create(
        workspace=workspace,
        name="Authorized",
        identifier="A" + uuid4().hex[:5],
        archived_at=timezone.now() if action == "delete" else None,
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=workspace_role)
    client = APIClient()
    client.force_authenticate(create_user)
    response = getattr(client, action)(f"/api/workspaces/{workspace.slug}/projects/{project.id}/archive/")
    assert response.status_code in [200, 204]
    project.refresh_from_db()
    assert bool(project.archived_at) == (action == "post")
