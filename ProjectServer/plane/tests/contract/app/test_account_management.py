"""Account identities can exist without projects; adding duties does not grant instance power."""

from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember, WorkspaceMember, User
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, LocalManagedAccount

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def owner(create_user):
    instance = Instance.objects.create(
        instance_name="账号联调管理员",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    return create_user


def test_local_account_creation_grants_no_project_then_adds_selected_duty(session_client, owner, workspace):
    response = session_client.post(
        "/api/quality-auth/accounts/",
        {"username": "rd-local-test", "display_name": "研发同事", "password": "test-only-password"},
        format="json",
    )
    assert response.status_code == 201, response.content
    user = User.objects.get(id=response.data["id"])
    assert user.check_password("test-only-password")
    assert not WorkspaceMember.objects.filter(member=user).exists()
    assert not ProjectMember.objects.filter(member=user).exists()
    assert LocalManagedAccount.objects.filter(user=user, created_by=owner).exists()
    project = Project.objects.create(workspace=workspace, name="后续安排项目", identifier="ACCOUNTJOIN")
    ProjectMember.objects.create(project=project, member=owner, role=20)
    target = f"/api/quality-auth/accounts/{workspace.slug}/projects/{project.id}/members/"
    joined = session_client.post(target, {"user_id": str(user.id), "role": "TECHNICIAN"}, format="json")
    assert joined.status_code == 200, joined.content
    assert BusinessRole.objects.get(project=project, user=user).role == "TECHNICIAN"
    assert not InstanceAdmin.objects.filter(user=user).exists()
    assert "test-only-password" not in str(response.data)


def test_non_admin_cannot_create_users_or_assign_project_roles(session_client, owner, workspace, create_user):
    other = User.objects.create(email="unprivileged@accounts.invalid", username="unprivileged")
    session_client.force_authenticate(user=other)
    denied = session_client.post(
        "/api/quality-auth/accounts/", {"username": "illegal-user", "password": "test-only-password"}, format="json"
    )
    assert denied.status_code == 403
    assert not User.objects.filter(username="illegal-user").exists()
    listing = session_client.get("/api/quality-auth/accounts/")
    assert listing.data == {"can_manage": False, "results": []}


def test_add_member_cannot_replace_existing_project_duties(session_client, owner, workspace):
    user = User.objects.create(email="existing@accounts.invalid", username="existing")
    project = Project.objects.create(workspace=workspace, name="已有成员", identifier="EXISTING")
    ProjectMember.objects.create(project=project, member=owner, role=20)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    ProjectMember.objects.create(workspace=workspace, project=project, member=user, role=15)
    binding = BusinessRole.objects.create(
        project=project, user=user, role="PLATFORM_ADMIN", additional_roles=["TECHNICIAN"]
    )
    response = session_client.post(
        f"/api/quality-auth/accounts/{workspace.slug}/projects/{project.id}/members/",
        {"user_id": str(user.id), "role": "REGRESSION_TESTER"},
        format="json",
    )
    assert response.status_code == 409, response.content
    binding.refresh_from_db()
    assert binding.role == "PLATFORM_ADMIN" and binding.additional_roles == ["TECHNICIAN"]


def test_managed_unassigned_account_cannot_self_create_workspace_or_project(session_client, workspace):
    user = User.objects.create(email="managed@accounts.invalid", username="managed")
    LocalManagedAccount.objects.create(user=user, created_by=user)
    session_client.force_authenticate(user=user)
    response = session_client.post("/api/workspaces/", {"name": "绕过分配", "slug": "bypass-managed"}, format="json")
    assert response.status_code == 403, response.content
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "自行授权", "identifier": "BYPASS"}, format="json"
    )
    assert response.status_code == 403, response.content


def test_external_account_cannot_mint_or_use_native_personal_api_key(session_client, api_client, create_user):
    from django.urls import reverse
    from plane.quality.models import PlatformAccount
    from plane.db.models import APIToken

    PlatformAccount.objects.create(
        user=create_user, source_instance="authority", external_user_id=42, source_username="collector"
    )
    response = session_client.post(reverse("api-tokens"), {"label": "旁路应拒绝"}, format="json")
    assert response.status_code == 403, response.content
    assert not APIToken.objects.filter(user=create_user).exists()
    token = APIToken.objects.create(user=create_user, label="已有旁路")
    api_client.force_authenticate(user=None)
    api_client.credentials(HTTP_X_API_KEY=token.token)
    assert api_client.get("/api/v1/users/me/").status_code in {401, 403}


def test_managed_native_api_key_cannot_create_a_project(api_client, workspace):
    from plane.db.models import APIToken

    user = User.objects.create(email="native-engineer@accounts.invalid", username="native-engineer")
    LocalManagedAccount.objects.create(user=user, created_by=user)
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    token = APIToken.objects.create(user=user, label="研发API")
    api_client.credentials(HTTP_X_API_KEY=token.token)
    response = api_client.post(
        f"/api/v1/workspaces/{workspace.slug}/projects/", {"name": "越权项目", "identifier": "APIBYPASS"}, format="json"
    )
    assert response.status_code == 403, response.content


def test_retired_source_identity_cannot_join_native_project(session_client, owner, workspace, mocker):
    from plane.quality.models import PlatformAccount

    project = Project.objects.create(workspace=workspace, name="本地账号准入", identifier="NATONLY")
    person = User.objects.create(username="old-source", email="old-source@test.invalid")
    PlatformAccount.objects.create(
        user=person, source_instance="authority", external_user_id=42, source_username="old-source"
    )
    outbound = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("no source lookup"))
    response = session_client.post(
        f"/api/quality-auth/accounts/{workspace.slug}/projects/{project.id}/members/",
        {"user_id": str(person.id), "role": "TECHNICIAN"},
        format="json",
    )
    assert response.status_code in {400, 403, 404}, response.content
    assert not ProjectMember.objects.filter(project=project, member=person, is_active=True).exists()
    outbound.assert_not_called()


def test_new_project_starts_with_explicit_management_duties(session_client, workspace, create_user):
    from plane.quality.permissions import strict, roles_for

    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/", {"name": "默认隔离项目", "identifier": "NEWROLE"}, format="json"
    )
    assert response.status_code == 201, response.content
    project_id = response.data["id"]
    assert strict(project_id)
    assert roles_for(project_id, create_user.id) == {"PROJECT_MANAGER"}


def test_project_admin_can_find_existing_platform_people_without_granting_project_access(
    session_client, workspace, create_user
):
    from plane.quality.models import ProjectRolePolicy

    project = Project.objects.create(workspace=workspace, name="人员选择", identifier="PEOPLE")
    ProjectMember.objects.create(workspace=workspace, project=project, member=create_user, role=20)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="PLATFORM_ADMIN")
    outside = User.objects.create(username="existing-outside-rd", email="existing-outside-rd@example.invalid")
    response = session_client.get(
        "/api/quality-auth/accounts/",
        {"search": "existing-outside", "workspace_slug": workspace.slug, "project_id": str(project.id)},
    )
    assert response.status_code == 200, response.content
    assert response.data["can_manage"] and [x["id"] for x in response.data["results"]] == [str(outside.id)]
    assert not ProjectMember.objects.filter(project=project, member=outside).exists()
    added = session_client.post(
        f"/api/quality-auth/accounts/{workspace.slug}/projects/{project.id}/members/",
        {"user_id": str(outside.id), "role": "TECHNICIAN"},
        format="json",
    )
    assert added.status_code == 200, added.content
    assert BusinessRole.objects.get(project=project, user=outside).role == "TECHNICIAN"
    other = Project.objects.create(workspace=workspace, name="不可管理", identifier="OTHERPEOPLE")
    denied = session_client.get(
        "/api/quality-auth/accounts/", {"workspace_slug": workspace.slug, "project_id": str(other.id)}
    )
    assert denied.status_code == 200


def test_external_directory_never_provisions_platform_accounts(session_client, owner, workspace, mocker):
    from plane.quality.models import PlatformAccount

    project = Project.objects.create(workspace=workspace, name="本地人员目录", identifier="LOCALDIR")
    outbound = mocker.patch("plane.quality.platform.fetch", side_effect=AssertionError("no external directory"))
    before = User.objects.count()
    response = session_client.get(
        "/api/quality-auth/accounts/",
        {"workspace_slug": workspace.slug, "project_id": str(project.id), "source_instance": "data-main"},
    )
    assert response.status_code == 400, response.content
    assert not response.data.get("external_results")
    added = session_client.post(
        f"/api/quality-auth/accounts/{workspace.slug}/projects/{project.id}/members/",
        {"source_instance": "data-main", "external_user_id": 72, "role": "TECHNICIAN"},
        format="json",
    )
    assert added.status_code == 400, added.content
    assert User.objects.count() == before
    assert not PlatformAccount.objects.exists()
    outbound.assert_not_called()


def test_profile_projects_have_real_links_and_exclude_revoked_workspace(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="可进入的项目", identifier="MYPRJ")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    BusinessRole.objects.create(
        project=project, user=create_user, role="PLATFORM_ADMIN", additional_roles=["PROJECT_MANAGER"]
    )
    r = session_client.get("/api/quality-auth/account-security/")
    assert r.status_code == 200, r.content
    row = next(x for x in r.data["project_duties"] if x["project"] == project.name)
    assert row["project_id"] == str(project.id) and row["identifier"] == "MYPRJ"
    assert row["url"] == f"/{workspace.slug}/p/MYPRJ/issues/"
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    r = session_client.get("/api/quality-auth/account-security/")
    assert r.data["project_duties"] == []
