"""One administrator identity, without turning project managers into global admins."""

from uuid import uuid4
from types import SimpleNamespace
import pytest
from django.utils import timezone
from plane.db.models import User, Project, ProjectMember, WorkspaceMember
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, BusinessRoleEvent, ProjectRolePolicy, PlatformAccount
from plane.quality import permissions

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_repeated_administrator_grant_revoke_restores_existing_identity(scope, session_client):
    from plane.license.models import InstanceConfiguration

    project, actor, instance = scope
    InstanceAdmin.objects.create(instance=instance, user=actor)
    target = User.objects.create(username="repeat-admin", email="repeat-admin@test.invalid")
    original_id = None
    for enabled in [True, False, True, False, True]:
        response = session_client.patch(
            "/api/quality-auth/accounts/", {"user_id": str(target.id), "administrator": enabled}, format="json"
        )
        assert response.status_code == 200, response.data
        assert response.data["is_administrator"] is enabled
        assert permissions.is_administrator(target) is enabled
        record = InstanceAdmin.all_objects.get(instance=instance, user=target)
        original_id = original_id or record.id
        assert record.id == original_id
        assert (record.deleted_at is None) is enabled
    assert InstanceConfiguration.objects.filter(category="QUALITY_ADMIN_AUDIT").count() == 5
    assert InstanceAdmin.objects.filter(instance=instance, user=actor).exists()


@pytest.fixture
def scope(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="统一管理员", identifier="UNIFIED")
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    instance = Instance.objects.create(
        instance_name="统一管理",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    return project, create_user, instance


def test_canonical_admin_has_every_project_capability_without_duplicate_duties(scope):
    project, user, instance = scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    assert permissions.is_administrator(user)
    assert permissions.roles_for(project.id, user.id) == {"PLATFORM_ADMIN"}
    assert all(permissions.capable(project.id, user.id, cap) for cap in permissions.ALL_CAPABILITIES)
    WorkspaceMember.objects.filter(workspace=project.workspace, member=user).update(is_active=False)
    assert permissions.roles_for(project.id, user.id) == set()
    assert not permissions.capable(project.id, user.id, "manage_test")


def test_native_project_admin_initializes_manager_only(scope):
    from plane.quality.roles import initialize_project_roles

    project, user, _ = scope
    ProjectRolePolicy.objects.filter(project=project).delete()
    ProjectMember.objects.filter(project=project, member=user).update(role=20)
    initialize_project_roles(project, user)
    assert permissions.roles_for(project.id, user.id) == {"PROJECT_MANAGER"}
    assert not permissions.is_administrator(user)


def test_old_initialize_provenance_is_not_global_but_explicit_admin_is(scope):
    project, user, _ = scope
    BusinessRole.objects.create(project=project, user=user, role="PLATFORM_ADMIN", additional_roles=["PROJECT_MANAGER"])
    event = BusinessRoleEvent.objects.create(
        project=project, user=user, role="PLATFORM_ADMIN+PROJECT_MANAGER", action="initialize", created_by=user
    )
    assert not permissions.is_administrator(user)
    assert permissions.roles_for(project.id, user.id) == {"PROJECT_MANAGER"}
    BusinessRoleEvent.objects.create(project=project, user=user, role="", action="enable", created_by=user)
    assert not permissions.is_administrator(user)
    event.action = "set_roles"
    event.save()
    assert permissions.is_administrator(user)


def test_manager_cannot_assign_administrator_even_before_strict_policy(scope, session_client):
    project, user, _ = scope
    ProjectRolePolicy.objects.filter(project=project).delete()
    ProjectMember.objects.filter(project=project, member=user).update(role=20)
    response = session_client.post(
        f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/roles/",
        {"user_id": str(user.id), "role": "PLATFORM_ADMIN"},
        format="json",
    )
    assert response.status_code == 403
    assert not BusinessRole.objects.filter(project=project, role="PLATFORM_ADMIN").exists()
    assert not InstanceAdmin.objects.filter(user=user).exists()


def test_instance_and_project_context_use_same_admin_flag(scope, session_client):
    from plane.license.api.permissions.instance import InstanceAdminPermission

    project, user, instance = scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    assert InstanceAdminPermission().has_permission(SimpleNamespace(user=user), None)
    response = session_client.get(f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/context/")
    assert response.status_code == 200
    assert response.data["is_administrator"] and response.data["can_manage_administrators"]
    user.is_active = False
    user.save()
    assert not permissions.is_administrator(user.id)


def test_external_role_string_and_stale_business_grant_never_bypass_authority(scope):
    project, user, _ = scope
    PlatformAccount.objects.create(
        user=user, source_instance="source", external_user_id=1, source_username="Admin", source_role="Admin"
    )
    BusinessRole.objects.create(project=project, user=user, role="PLATFORM_ADMIN")
    assert not permissions.is_administrator(user)


def test_source_admin_claim_never_grants_local_administrator(scope):
    from plane.quality.data_accounts import sync_administrator

    project, user, instance = scope
    actor = User.objects.create(username="local-actor", email="local-actor@test.invalid")
    InstanceAdmin.objects.create(instance=instance, user=actor)
    account = PlatformAccount.objects.create(
        user=user, source_instance="source", external_user_id=1, source_username="Admin", source_role="Admin"
    )
    config = {"configured_by": str(actor.id), "service_token": "synthetic"}
    sync_administrator(account, {"role": "Admin"}, config, {"administrator": True})
    assert not permissions.is_administrator(user)
    assert not InstanceAdmin.objects.filter(user=user).exists()


@pytest.mark.parametrize("source_role", ["TeamLeader", "Annotator", "Auditor", "Collector"])
@pytest.mark.parametrize("local_role", ["TECHNICIAN", "REGRESSION_TESTER", "PROJECT_MANAGER"])
def test_first_default_reporter_then_local_role_survives_login(scope, source_role, local_role):
    from plane.quality.account_projects import provision_projects
    from plane.quality.models import PlatformProject

    project, user, instance = scope
    account = PlatformAccount.objects.create(
        user=user, source_instance="source", external_user_id=1, source_username="person", source_role=source_role
    )
    PlatformProject.objects.create(project=project, source_instance="source", external_project_id=7)
    config = {"configured_by": str(user.id), "service_token": "test-only"}
    fetch = lambda *a, **kw: {"projects": [{"id": 7}], "administrator": False}
    provision_projects(account, {"role": source_role}, config, fetch)
    binding = BusinessRole.objects.get(project=project, user=user)
    assert binding.role == "REPORTER"
    binding.role = local_role
    binding.save()
    BusinessRoleEvent.objects.create(
        project=project, user=user, role=local_role, previous_role="REPORTER", action="set_roles", created_by=user
    )
    provision_projects(account, {"role": source_role}, config, fetch)
    binding.refresh_from_db()
    assert binding.role == local_role
    assert not permissions.is_administrator(user)


def test_account_admin_grant_revoke_is_explicit_and_last_admin_protected(scope, session_client):
    project, user, instance = scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    other = User.objects.create(email="newadmin@admin.invalid", username="newadmin")
    endpoint = "/api/quality-auth/accounts/"
    denied = session_client.patch(endpoint, {"user_id": str(user.id), "administrator": False}, format="json")
    assert denied.status_code == 400
    granted = session_client.patch(endpoint, {"user_id": str(other.id), "administrator": True}, format="json")
    assert granted.status_code == 200 and permissions.is_administrator(other)
    revoked = session_client.patch(endpoint, {"user_id": str(other.id), "administrator": False}, format="json")
    assert revoked.status_code == 200 and not permissions.is_administrator(other)


def test_retired_source_claim_cannot_override_manual_platform_administrator(scope):
    from plane.quality.data_accounts import sync_administrator

    project, user, instance = scope
    actor = User.objects.create(username="claim-actor", email="claim-actor@test.invalid")
    InstanceAdmin.objects.create(instance=instance, user=actor)
    account = PlatformAccount.objects.create(
        user=user, source_instance="source", external_user_id=1, source_username="person", source_role="Admin"
    )
    for role in ["Admin", "Auditor", "Collector"]:
        sync_administrator(
            account,
            {"role": role},
            {"configured_by": str(actor.id), "service_token": "synthetic"},
            {"administrator": True},
        )
        assert not permissions.is_administrator(user)
    assert not InstanceAdmin.objects.filter(user=user).exists()


@pytest.mark.parametrize(
    "source_role,expected",
    [
        ("Admin", "PLATFORM_ADMIN"),
        ("Manager", "PROJECT_MANAGER"),
        ("TeamLeader", "REPORTER"),
        ("Annotator", "REPORTER"),
        ("Auditor", "REPORTER"),
        ("Collector", "REPORTER"),
    ],
)
def test_first_source_role_is_fixed_even_with_legacy_role_map(scope, source_role, expected):
    from plane.quality.account_projects import provision_projects
    from plane.quality.models import PlatformProject

    project, user, instance = scope
    account = PlatformAccount.objects.create(
        user=user, source_instance="source", external_user_id=1, source_username="person", source_role=source_role
    )
    PlatformProject.objects.create(project=project, source_instance="source", external_project_id=7)
    config = {
        "configured_by": str(user.id),
        "service_token": "test-only",
        "login_role_map": {source_role: "TECHNICIAN"},
    }
    provision_projects(
        account,
        {"role": source_role},
        config,
        lambda *a, **kw: {"projects": [{"id": 7}], "administrator": source_role == "Admin"},
    )
    binding = BusinessRole.objects.get(project=project, user=user)
    assert binding.role == expected
    binding.role = "REGRESSION_TESTER"
    binding.save()
    provision_projects(
        account,
        {"role": source_role},
        config,
        lambda *a, **kw: {"projects": [{"id": 7}], "administrator": source_role == "Admin"},
    )
    binding.refresh_from_db()
    assert binding.role == "REGRESSION_TESTER"


def test_native_admin_delete_uses_same_last_admin_protection(scope, session_client):
    project, user, instance = scope
    row = InstanceAdmin.objects.create(instance=instance, user=user)
    response = session_client.delete(f"/api/instances/admins/{row.id}/")
    assert response.status_code == 400
    assert InstanceAdmin.objects.filter(pk=row.pk).exists()


def test_source_admin_revocation_override_survives_live_reverification(scope, session_client):
    from plane.quality.data_accounts import sync_administrator

    project, user, instance = scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    other = User.objects.create(email="verifiedadmin@admin.invalid", username="verifiedadmin")
    account = PlatformAccount.objects.create(
        user=other, source_instance="source", external_user_id=4, source_username="verified", source_role="Admin"
    )
    config = {"configured_by": str(user.id), "service_token": "test-only"}
    sync_administrator(account, {"role": "Admin"}, config, {"administrator": True})
    row = InstanceAdmin.objects.create(instance=instance, user=other)
    assert session_client.delete(f"/api/instances/admins/{row.id}/").status_code == 204
    assert not permissions.is_administrator(other)
    sync_administrator(account, {"role": "Admin"}, config, {"administrator": True})
    assert not permissions.is_administrator(other)


def test_native_member_serializers_share_administrator_flag(scope):
    from plane.app.serializers.project import (
        ProjectMemberSerializer,
        ProjectMemberAdminSerializer,
        ProjectMemberRoleSerializer,
    )
    from plane.app.serializers.workspace import WorkSpaceMemberSerializer, WorkspaceMemberAdminSerializer

    project, user, instance = scope
    member = ProjectMember.objects.get(project=project, member=user)
    workspace_member = WorkspaceMember.objects.get(workspace=project.workspace, member=user)
    for serializer, obj in [
        (ProjectMemberRoleSerializer, member),
        (ProjectMemberSerializer, member),
        (ProjectMemberAdminSerializer, member),
        (WorkSpaceMemberSerializer, workspace_member),
        (WorkspaceMemberAdminSerializer, workspace_member),
    ]:
        assert serializer(obj).data["is_administrator"] is False
    InstanceAdmin.objects.create(instance=instance, user=user)
    for serializer, obj in [
        (ProjectMemberRoleSerializer, member),
        (ProjectMemberSerializer, member),
        (ProjectMemberAdminSerializer, member),
        (WorkSpaceMemberSerializer, workspace_member),
        (WorkspaceMemberAdminSerializer, workspace_member),
    ]:
        assert serializer(obj).data["is_administrator"] is True


def test_explicit_grant_normalizes_old_administrator_role(scope, session_client):
    project, user, instance = scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    other = User.objects.create(email="oldrole@admin.invalid", username="oldrole")
    row = InstanceAdmin.objects.create(instance=instance, user=other, role=15)
    response = session_client.patch(
        "/api/quality-auth/accounts/", {"user_id": str(other.id), "administrator": True}, format="json"
    )
    assert response.status_code == 200 and response.data["is_administrator"]
    row.refresh_from_db()
    assert row.role == 20


@pytest.mark.parametrize("source_role", ["TeamLeader", "Annotator", "Auditor", "Collector"])
def test_retired_source_login_cannot_create_or_reassign_platform_accounts(scope, mocker, source_role):
    from rest_framework.test import APIClient

    project, user, instance = scope
    outbound = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("No source login"))
    before = User.objects.count()
    response = APIClient().post(
        "/api/quality-auth/data-login/",
        {"source_instance": "source", "username": "source-person", "password": "synthetic"},
        format="json",
    )
    assert response.status_code == 404, response.content
    assert User.objects.count() == before
    assert not PlatformAccount.objects.exists()
    outbound.assert_not_called()
