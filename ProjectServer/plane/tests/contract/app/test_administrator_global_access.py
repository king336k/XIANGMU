"""A canonical administrator manages every workspace/project without manual membership."""

from uuid import uuid4
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import User, Workspace, WorkspaceMember, Project, ProjectMember
from plane.license.models import Instance, InstanceAdmin

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def global_admin():
    admin = User.objects.create(username="global-admin", email="global@test.invalid")
    keeper = User.objects.create(username="keeper-admin", email="keeper@test.invalid")
    instance = Instance.objects.create(
        instance_name="all",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    InstanceAdmin.objects.create(instance=instance, user=admin)
    InstanceAdmin.objects.create(instance=instance, user=keeper)
    owner = User.objects.create(username="space-owner", email="owner@test.invalid")
    workspace = Workspace.objects.create(name="他人工作区", slug="global-audit", owner=owner)
    project = Project.objects.create(workspace=workspace, name="他人项目", identifier="GLOBAL")
    client = APIClient()
    client.force_authenticate(admin)
    return client, admin, keeper, workspace, project


def test_admin_automatically_sees_and_operates_unjoined_and_future_scopes(global_admin):
    client, admin, _, workspace, project = global_admin
    assert not WorkspaceMember.objects.filter(workspace=workspace, member=admin).exists()
    response = client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/context/")
    assert response.status_code == 200, response.content
    assert response.data["is_administrator"] and all(response.data["capabilities"].values())
    assert WorkspaceMember.objects.get(workspace=workspace, member=admin).role == 20
    assert ProjectMember.objects.get(project=project, member=admin).role == 20
    future = Project.objects.create(workspace=workspace, name="新项目", identifier="FUTURE")
    assert (
        client.post(
            f"/api/workspaces/{workspace.slug}/projects/{future.id}/quality/defects/",
            {"title": "管理员验收"},
            format="json",
        ).status_code
        == 201
    )


@pytest.mark.parametrize("prior", [None, 5, 15, 20])
def test_revoking_admin_restores_previous_access_instead_of_leaking_global_memberships(global_admin, prior):
    client, admin, keeper, workspace, project = global_admin
    if prior:
        WorkspaceMember.objects.create(workspace=workspace, member=admin, role=prior)
        ProjectMember.objects.create(project=project, member=admin, role=prior)
    response = client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/context/")
    assert response.status_code == 200, response.content
    manager = APIClient()
    manager.force_authenticate(keeper)
    response = manager.patch(
        "/api/quality-auth/accounts/", {"user_id": str(admin.id), "administrator": False}, format="json"
    )
    assert response.status_code == 200, response.content
    if prior:
        assert WorkspaceMember.objects.get(workspace=workspace, member=admin).role == prior
        assert ProjectMember.objects.get(project=project, member=admin).role == prior
    else:
        assert not WorkspaceMember.objects.filter(workspace=workspace, member=admin, is_active=True).exists()
        assert not ProjectMember.objects.filter(project=project, member=admin, is_active=True).exists()
        assert client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/context/").status_code == 403


def test_wrong_workspace_slug_and_disabled_admin_still_denied(global_admin):
    client, admin, _, workspace, project = global_admin
    other = Workspace.objects.create(name="其他", slug="global-other", owner=admin)
    assert client.get(f"/api/workspaces/{other.slug}/projects/{project.id}/quality/context/").status_code == 403
    User.objects.filter(pk=admin.pk).update(is_active=False)
    admin.refresh_from_db()
    assert client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/context/").status_code == 403


def test_admin_scope_controls_cannot_turn_off_effective_global_authority(global_admin):
    client, admin, keeper, workspace, project = global_admin
    endpoint = f"/api/quality-auth/member-scopes/{admin.id}/"
    response = client.get(endpoint)
    row = next(row for row in response.data["results"] if row["id"] == str(workspace.id))
    denied = client.post(
        endpoint,
        {
            "changes": [
                {"kind": "workspace", "id": str(workspace.id), "access_role": 0, "expected_revision": row["revision"]}
            ]
        },
        format="json",
    )
    assert denied.status_code == 400, denied.content
    assert WorkspaceMember.objects.get(workspace=workspace, member=admin).role == 20


def test_stale_projection_is_removed_after_out_of_band_admin_revocation(global_admin):
    client, admin, _, workspace, project = global_admin
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    assert client.get(base + "context/").status_code == 200
    InstanceAdmin.objects.filter(user=admin).delete()
    assert client.get(base + "context/").status_code == 403
    assert not ProjectMember.objects.filter(project=project, member=admin, is_active=True).exists()


def test_replaced_projection_row_is_still_revoked_without_access_residue(global_admin):
    client, admin, keeper, workspace, project = global_admin
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/context/"
    assert client.get(url).status_code == 200
    # Simulate native deletion maintenance replacing a membership row while admin remains global.
    ProjectMember.objects.filter(project=project, member=admin).delete()
    assert client.get(url).status_code == 200
    manager = APIClient()
    manager.force_authenticate(keeper)
    assert (
        manager.patch(
            "/api/quality-auth/accounts/", {"user_id": str(admin.id), "administrator": False}, format="json"
        ).status_code
        == 200
    )
    assert not ProjectMember.objects.filter(project=project, member=admin, is_active=True).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_admin_requests_project_each_scope_once_and_revoke_without_residue(global_admin):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from plane.quality.administrator_access import synchronize_administrator_access
    from plane.quality.administrators import set_administrator
    from plane.quality.models import AdministratorAccessGrant

    _, admin, keeper, workspace, project = global_admin

    def sync():
        close_old_connections()
        try:
            synchronize_administrator_access(User.objects.get(pk=admin.pk))
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: sync(), range(2)))
    assert ProjectMember.objects.filter(project=project, member=admin, is_active=True, role=20).count() == 1
    assert WorkspaceMember.objects.filter(workspace=workspace, member=admin, is_active=True, role=20).count() == 1
    assert AdministratorAccessGrant.objects.filter(user=admin).count() == 2
    set_administrator(keeper, admin, False)
    assert not ProjectMember.objects.filter(project=project, member=admin, is_active=True).exists()
    assert not WorkspaceMember.objects.filter(workspace=workspace, member=admin, is_active=True).exists()


def test_physically_removed_auto_membership_recreates_then_revokes_cleanly(global_admin):
    client, admin, keeper, workspace, project = global_admin
    path = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/context/"
    assert client.get(path).status_code == 200
    ProjectMember.all_objects.filter(project=project, member=admin).delete()
    response = client.get(path)
    assert response.status_code == 200, response.content
    manager = APIClient()
    manager.force_authenticate(keeper)
    revoked = manager.patch(
        "/api/quality-auth/accounts/", {"user_id": str(admin.id), "administrator": False}, format="json"
    )
    assert revoked.status_code == 200, revoked.content
    assert not ProjectMember.objects.filter(project=project, member=admin, is_active=True).exists()
