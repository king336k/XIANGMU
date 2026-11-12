"""Effective administrators manage native access only inside active writable memberships."""

from uuid import uuid4
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import User, Project, ProjectMember, WorkspaceMember, Workspace
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, ProjectRolePolicy
from plane.quality.permissions import is_administrator

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def access_scope(workspace, create_user):
    instance = Instance.objects.create(
        instance_name="access", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    actor = User.objects.create(username="effectiveadmin", email="effectiveadmin@test.invalid")
    InstanceAdmin.objects.create(instance=instance, user=actor)
    ws = WorkspaceMember.objects.create(workspace=workspace, member=actor, role=15)
    project = Project.objects.create(workspace=workspace, name="访问权限", identifier="ACCESS")
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    own = ProjectMember.objects.create(project=project, member=actor, role=15)
    target = User.objects.create(username="accessmember", email="accessmember@test.invalid")
    target_ws = WorkspaceMember.objects.create(workspace=workspace, member=target, role=15)
    target_project = ProjectMember.objects.create(project=project, member=target, role=15)
    client = APIClient()
    client.force_login(actor)
    return client, project, actor, target, ws, own, target_ws, target_project


@pytest.mark.parametrize("identity", ["canonical", "legacy"])
@pytest.mark.parametrize("new_role", [5, 15, 20])
def test_effective_admin_native15_can_change_project_access(access_scope, identity, new_role):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    if identity == "legacy":
        InstanceAdmin.objects.filter(user=actor).delete()
        BusinessRole.objects.create(project=project, user=actor, role="PLATFORM_ADMIN")
    response = client.patch(
        f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/members/{target_project.id}/",
        {"role": new_role},
        format="json",
    )
    assert response.status_code == 200, response.data
    target_project.refresh_from_db()
    assert target_project.role == new_role
    assert not is_administrator(target)


@pytest.mark.parametrize("new_role", [5, 15, 20])
def test_effective_admin_native15_can_change_workspace_access(access_scope, new_role):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    response = client.patch(
        f"/api/workspaces/{project.workspace.slug}/members/{target_ws.id}/", {"role": new_role}, format="json"
    )
    assert response.status_code == 200, response.data
    target_ws.refresh_from_db()
    assert target_ws.role == new_role
    assert not is_administrator(target)


def test_effective_admin_can_deactivate_and_reactivate_other_project_member(access_scope):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    url = f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/members/{target_project.id}/"
    for enabled in [False, True]:
        response = client.patch(url, {"is_active": enabled}, format="json")
        assert response.status_code == 200, response.data
        target_project.refresh_from_db()
        assert target_project.is_active is enabled


@pytest.mark.parametrize("scope", ["project", "workspace"])
def test_effective_admin_can_remove_higher_native_member_without_global_revoke(access_scope, scope):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    target_ws.role = 20
    target_ws.save()
    target_project.role = 20
    target_project.save()
    url = f"/api/workspaces/{project.workspace.slug}/" + (
        f"projects/{project.id}/members/{target_project.id}/" if scope == "project" else f"members/{target_ws.id}/"
    )
    response = client.delete(url)
    assert response.status_code == 204, response.data
    target_project.refresh_from_db()
    assert not target_project.is_active
    assert InstanceAdmin.objects.filter(user=actor).exists()


@pytest.mark.parametrize(
    "denial", ["project_guest", "workspace_guest", "workspace_inactive", "project_inactive", "actor_inactive"]
)
def test_former_admin_does_not_bypass_membership_boundaries(access_scope, denial):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    # Global admins now manage every scope; this boundary applies after revocation.
    InstanceAdmin.objects.filter(user=actor).delete()
    if denial == "project_guest":
        own.role = 5
        own.save()
    if denial == "workspace_guest":
        ws.role = 5
        ws.save()
    if denial == "workspace_inactive":
        ws.is_active = False
        ws.save()
    if denial == "project_inactive":
        own.is_active = False
        own.save()
    if denial == "actor_inactive":
        actor.is_active = False
        actor.save()
    response = client.patch(
        f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/members/{target_project.id}/",
        {"role": 5},
        format="json",
    )
    assert response.status_code in {401, 403}, response.data
    target_project.refresh_from_db()
    assert target_project.role == 15


def test_former_admin_outside_private_project_or_workspace_cannot_manage_access(access_scope, create_user):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    # Global admins now manage every scope; this boundary applies after revocation.
    InstanceAdmin.objects.filter(user=actor).delete()
    other = Project.objects.create(
        workspace=project.workspace, name="未加入私有项目", identifier="NOPRIVATE", network=0
    )
    member = ProjectMember.objects.create(project=other, member=target, role=15)
    assert (
        client.patch(
            f"/api/workspaces/{project.workspace.slug}/projects/{other.id}/members/{member.id}/",
            {"role": 5},
            format="json",
        ).status_code
        == 403
    )
    space = Workspace.objects.create(owner=create_user, name="未加入空间", slug="other-access")
    foreign = WorkspaceMember.objects.create(workspace=space, member=target, role=15)
    assert (
        client.patch(f"/api/workspaces/{space.slug}/members/{foreign.id}/", {"role": 5}, format="json").status_code
        == 403
    )


def test_ordinary_member_cannot_write_access_or_grant_global_admin(access_scope):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    InstanceAdmin.objects.filter(user=actor).delete()
    BusinessRole.objects.create(project=project, user=actor, role="REPORTER")
    assert (
        client.patch(
            f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/members/{target_project.id}/",
            {"is_active": False},
            format="json",
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/workspaces/{project.workspace.slug}/members/{target_ws.id}/", {"role": 20}, format="json"
        ).status_code
        == 403
    )
    own.role = 20
    own.save()
    assert (
        client.patch(
            "/api/quality-auth/accounts/", {"user_id": str(target.id), "administrator": True}, format="json"
        ).status_code
        == 403
    )


def test_effective_admin_self_remove_remains_explicit_leave_only(access_scope):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    assert (
        client.delete(f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/members/{own.id}/").status_code
        == 400
    )
    assert client.delete(f"/api/workspaces/{project.workspace.slug}/members/{ws.id}/").status_code == 400


@pytest.mark.parametrize("scope", ["workspace", "project"])
def test_effective_admin_native15_can_change_settings(access_scope, scope):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    url = f"/api/workspaces/{project.workspace.slug}/" + (f"projects/{project.id}/" if scope == "project" else "")
    response = client.patch(url, {"name": "最高管理员更新设置"}, format="json")
    assert response.status_code == 200, response.data


def test_effective_admin_native15_can_set_project_defaults_and_guest_visibility(access_scope):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    response = client.patch(
        f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/",
        {"default_assignee": str(target.id), "guest_view_all_features": True},
        format="json",
    )
    assert response.status_code == 200, response.data
    project.refresh_from_db()
    assert project.default_assignee_id == target.id and project.guest_view_all_features


@pytest.mark.parametrize("scope", ["workspace", "project"])
@pytest.mark.parametrize("boundary", ["guest", "inactive", "foreign"])
def test_settings_write_preserves_former_admin_membership_scope(access_scope, scope, boundary, create_user):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    # Global admins now manage every scope; this boundary applies after revocation.
    InstanceAdmin.objects.filter(user=actor).delete()
    url = f"/api/workspaces/{project.workspace.slug}/" + (f"projects/{project.id}/" if scope == "project" else "")
    if boundary == "guest":
        membership = own if scope == "project" else ws
        membership.role = 5
        membership.save()
    if boundary == "inactive":
        membership = own if scope == "project" else ws
        membership.is_active = False
        membership.save()
    if boundary == "foreign":
        if scope == "project":
            foreign = Project.objects.create(
                workspace=project.workspace, name="没有加入", identifier="FOREIGNDEF", network=0
            )
            url = f"/api/workspaces/{project.workspace.slug}/projects/{foreign.id}/"
        else:
            space = Workspace.objects.create(owner=create_user, name="没有加入空间", slug="foreign-settings")
            url = f"/api/workspaces/{space.slug}/"
    response = client.patch(url, {"name": "禁止越范围保存"}, format="json")
    assert response.status_code in {403, 404}, response.data


@pytest.mark.parametrize("scope", ["workspace", "project"])
def test_effective_admin_native15_can_delete_in_scope_fixture(access_scope, scope, mocker):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    mocker.patch("plane.app.views.workspace.base.track_event.delay")
    mocker.patch("plane.app.views.project.base.webhook_activity.delay")
    url = f"/api/workspaces/{project.workspace.slug}/" + (f"projects/{project.id}/" if scope == "project" else "")
    response = client.delete(url)
    assert response.status_code == 204, getattr(response, "data", None)
    assert InstanceAdmin.objects.filter(user=actor).exists()


@pytest.mark.parametrize("scope", ["workspace", "project"])
@pytest.mark.parametrize("boundary", ["guest", "inactive", "foreign"])
def test_former_admin_destructive_operation_never_escapes_active_writable_scope(
    access_scope, scope, boundary, create_user, mocker
):
    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    # Global admins now manage every scope; this boundary applies after revocation.
    InstanceAdmin.objects.filter(user=actor).delete()
    mocker.patch("plane.app.views.workspace.base.track_event.delay")
    mocker.patch("plane.app.views.project.base.webhook_activity.delay")
    url = f"/api/workspaces/{project.workspace.slug}/" + (f"projects/{project.id}/" if scope == "project" else "")
    if boundary in {"guest", "inactive"}:
        membership = own if scope == "project" else ws
        if boundary == "guest":
            membership.role = 5
        else:
            membership.is_active = False
        membership.save()
    else:
        if scope == "project":
            foreign = Project.objects.create(
                workspace=project.workspace, name="私有项目不越权", identifier="NOACCESSDEL", network=0
            )
            url = f"/api/workspaces/{project.workspace.slug}/projects/{foreign.id}/"
        else:
            space = Workspace.objects.create(owner=create_user, name="外部空间", slug="outside-delete")
            url = f"/api/workspaces/{space.slug}/"
    response = client.delete(url)
    assert response.status_code in {403, 404}, getattr(response, "data", None)


def test_effective_admin_native15_can_invite_access20_without_global_grant(access_scope, mocker):
    from plane.db.models import WorkspaceMemberInvite

    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    mail = mocker.patch("plane.app.views.workspace.invite.workspace_invitation.delay")
    mocker.patch("plane.app.views.workspace.invite.track_event.delay")
    response = client.post(
        f"/api/workspaces/{project.workspace.slug}/invitations/",
        {"emails": [{"email": "invited-admin-access@test.invalid", "role": 20}]},
        format="json",
    )
    assert response.status_code == 200, response.data
    invitation = WorkspaceMemberInvite.objects.get(email="invited-admin-access@test.invalid")
    assert invitation.role == 20
    assert InstanceAdmin.objects.count() == 1 and InstanceAdmin.objects.filter(user=actor).exists()
    mail.assert_called_once()


def test_ordinary_native15_cannot_invite_access20(access_scope, mocker):
    from plane.db.models import WorkspaceMemberInvite

    client, project, actor, target, ws, own, target_ws, target_project = access_scope
    InstanceAdmin.objects.filter(user=actor).delete()
    mail = mocker.patch("plane.app.views.workspace.invite.workspace_invitation.delay")
    mocker.patch("plane.app.views.workspace.invite.track_event.delay")
    response = client.post(
        f"/api/workspaces/{project.workspace.slug}/invitations/",
        {"emails": [{"email": "ordinary-upgrade@test.invalid", "role": 20}]},
        format="json",
    )
    assert response.status_code == 400, response.data
    assert not WorkspaceMemberInvite.objects.filter(email="ordinary-upgrade@test.invalid").exists()
    mail.assert_not_called()
