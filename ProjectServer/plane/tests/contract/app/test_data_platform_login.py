"""Data-platform authority logs in new users without copying passwords or granting projects."""

from uuid import uuid4
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import User, WorkspaceMember, ProjectMember
from plane.license.models import Instance, InstanceAdmin

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def authority(create_user, mocker):
    from django.core.cache import cache
    from plane.quality.legacy_login import LoginThrottle

    key = LoginThrottle.cache_format % {"scope": LoginThrottle.scope, "ident": "127.0.0.1"}
    cache.delete(key)
    instance = Instance.objects.create(
        instance_name="本机账号联调", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=create_user)
    config = {
        "kind": "data_platform",
        "base_url": "https://authority.example",
        "allowed_hosts": ["authority.example"],
        "login_enabled": True,
        "login_auto_provision": True,
        "configured_by": str(create_user.id),
    }
    mocker.patch("plane.quality.data_accounts.read_connection", return_value=config)
    login = mocker.patch(
        "plane.quality.data_accounts.authenticate_upstream",
        return_value=({"id": 42, "username": "admin", "status": "Active", "role": "Manager"}, "test-access-only"),
    )
    yield config, login
    cache.delete(key)


def post(client, **extra):
    return client.post(
        "/api/quality-auth/data-login/",
        {"source_instance": "data-main", "username": "admin", "password": "test-input-only", **extra},
        format="json",
    )


def test_new_authority_user_auto_links_identity_but_gets_no_project_or_instance_power(authority):
    from plane.quality.models import PlatformAccount

    client = APIClient()
    r = post(client)
    assert r.status_code == 200, r.content
    account = PlatformAccount.objects.get(source_instance="data-main", external_user_id=42)
    assert not account.user.has_usable_password()
    assert account.user.username != "admin"
    assert account.user.display_name == "admin"
    assert not ProjectMember.objects.filter(member=account.user).exists()
    assert not WorkspaceMember.objects.filter(member=account.user).exists()
    assert not InstanceAdmin.objects.filter(user=account.user).exists()
    assert "test-input-only" not in str(dict(client.session))
    assert "test-access-only" not in str(dict(client.session))
    assert "password" not in r.data and "access_token" not in r.data
    assert r.data["next"].startswith("/settings/")
    first = account.user_id
    assert post(APIClient()).status_code == 200
    assert PlatformAccount.objects.get(id=account.id).user_id == first


def test_same_name_does_not_merge_an_existing_native_account(authority, create_user):
    from plane.quality.models import PlatformAccount

    before = User.objects.count()
    r = post(APIClient())
    assert r.status_code == 200, r.content
    account = PlatformAccount.objects.get(source_instance="data-main", external_user_id=42)
    assert account.user_id != create_user.id
    assert User.objects.count() == before + 1


def test_disabled_or_unapproved_authority_never_provisions(authority):
    from plane.quality.models import PlatformAccount

    config, login = authority
    config["configured_by"] = str(uuid4())
    assert post(APIClient()).status_code == 403
    assert not PlatformAccount.objects.exists()
    config["configured_by"] = None
    assert post(APIClient()).status_code == 403


def test_data_login_requires_csrf_and_same_origin(authority):
    c = APIClient(enforce_csrf_checks=True)
    assert post(c).status_code == 403
    token = c.get("/auth/get-csrf-token/").data["csrf_token"]
    assert (
        c.post(
            "/api/quality-auth/data-login/",
            {"source_instance": "data-main", "username": "admin", "password": "test-only"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_ORIGIN="https://evil.invalid",
        ).status_code
        == 403
    )


def test_data_account_security_and_source_rename_recheck(authority, mocker):
    from plane.quality.models import PlatformAccount

    config, login = authority
    client = APIClient()
    assert post(client).status_code == 200
    mocker.patch(
        "plane.quality.data_accounts.source_user",
        return_value={
            "id": 42,
            "username": "renamed.user",
            "status": "Active",
            "role": "Collector",
            "email": "source@unit.invalid",
        },
    )
    response = client.get("/api/quality-auth/account-security/")
    assert response.status_code == 200, response.content
    assert response.data["username"] == "renamed.user"
    assert response.data["can_change_local_password"] is False
    assert response.data["platform_role"] == "Collector"
    me = client.get("/api/users/me/")
    assert me.status_code == 200, me.content
    assert me.data["username"] == "renamed.user"
    assert not me.data["email"].endswith("@accounts.invalid")
    assert client.post("/auth/set-password/", {"new_password": "test-password-only"}).status_code == 403
    account = PlatformAccount.objects.get(external_user_id=42)
    assert not account.user.has_usable_password()


def test_disabled_authority_session_is_removed(authority, mocker):
    from rest_framework.exceptions import AuthenticationFailed

    client = APIClient()
    assert post(client).status_code == 200
    mocker.patch("plane.quality.data_accounts.source_user", side_effect=AuthenticationFailed("disabled"))
    assert client.get("/api/quality-auth/account-security/").status_code == 401
    assert "_auth_user_id" not in client.session


def test_external_profile_cannot_change_authoritative_identity(authority, mocker):
    client = APIClient()
    assert post(client).status_code == 200
    mocker.patch(
        "plane.quality.data_accounts.source_user",
        return_value={
            "id": 42,
            "username": "admin",
            "status": "Active",
            "role": "Manager",
            "email": "admin@unit.invalid",
        },
    )
    response = client.patch("/api/users/me/", {"display_name": "冒用身份", "first_name": "任意名"}, format="json")
    assert response.status_code == 400, response.content
    profile = client.get("/api/quality-auth/account-security/")
    assert profile.status_code == 200
    assert profile.data["can_edit_identity"] is False
    assert profile.data["display_name"] == "admin"


def test_local_managed_profile_hides_internal_email(session_client, create_user):
    from plane.quality.models import LocalManagedAccount

    create_user.email = "local-test@accounts.invalid"
    create_user.save()
    LocalManagedAccount.objects.create(user=create_user, created_by=create_user)
    response = session_client.get("/api/quality-auth/account-security/")
    assert response.status_code == 200
    assert response.data["email"] == ""
    assert response.data["can_edit_identity"] is True


@pytest.mark.parametrize("path", ["/auth/sign-up/", "/auth/magic-sign-up/"])
def test_managed_accounts_cannot_bypass_admin_creation_with_other_signup_paths(authority, mocker, path):
    mocker.patch("plane.quality.data_accounts.managed_registration", return_value=True)
    response = APIClient().post(path, {"email": "new@unit.invalid", "password": "test-only-password"})
    assert response.status_code == 403, response.content


def test_generic_member_entry_cannot_bypass_source_project_revocation(authority, mocker, workspace):
    from plane.db.models import Project
    from plane.quality.models import PlatformAccount, PlatformProject

    client = APIClient()
    assert post(client).status_code == 200
    account = PlatformAccount.objects.get(external_user_id=42)
    project = Project.objects.create(workspace=workspace, name="来源已撤销", identifier="REVOKEDSRC")
    WorkspaceMember.objects.create(workspace=workspace, member=account.user, role=15)
    member = ProjectMember.objects.create(workspace=workspace, project=project, member=account.user, role=15)
    PlatformProject.objects.create(project=project, source_instance="data-main", external_project_id=7)
    authority[0]["service_token"] = "test-service-only"
    mocker.patch(
        "plane.quality.data_accounts.source_user",
        return_value={"id": 42, "username": "admin", "status": "Active", "role": "Manager"},
    )
    mocker.patch("plane.quality.data_accounts.authority_request", return_value={"projects": []})
    response = client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/context/")
    assert response.status_code == 403, response.content
    member.refresh_from_db()
    assert member.is_active is False


@pytest.mark.parametrize(
    "role,target",
    [
        ("REPORTER", "defects/"),
        ("REGRESSION_TESTER", "quality/"),
        ("TECHNICIAN", "defects/"),
        ("PROJECT_MANAGER", "issues/"),
    ],
)
def test_login_lands_in_current_business_duty(authority, mocker, workspace, role, target):
    from plane.db.models import Project
    from plane.quality.models import PlatformAccount, PlatformIdentity, BusinessRole

    client = APIClient()
    assert post(client).status_code == 200
    account = PlatformAccount.objects.get(external_user_id=42)
    project = Project.objects.create(workspace=workspace, name="岗位入口", identifier="DUTY")
    WorkspaceMember.objects.create(workspace=workspace, member=account.user, role=15)
    ProjectMember.objects.create(workspace=workspace, project=project, member=account.user, role=15)
    BusinessRole.objects.create(project=project, user=account.user, role=role)
    PlatformIdentity.objects.create(
        project=project,
        user=account.user,
        source_instance="data-main",
        external_user_id=42,
        created_by_id=authority[0]["configured_by"],
    )
    mocker.patch("plane.quality.platform.verify_identity")
    result = post(APIClient())
    assert result.status_code == 200, result.content
    assert result.data["next"].endswith(target)
