"""Workspace permission and project responsibilities remain separate."""

import pytest
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember, WorkspaceMember
from plane.quality.models import BusinessRole

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


def test_workspace_admin_sees_only_roles_in_projects_they_can_access(workspace, create_user):
    visible = Project.objects.create(workspace=workspace, name="Visible", identifier="MBV")
    hidden = Project.objects.create(workspace=workspace, name="Hidden", identifier="MBH")
    ProjectMember.objects.create(project=visible, member=create_user, role=20)
    BusinessRole.objects.create(project=visible, user=create_user, role="PROJECT_MANAGER", created_by=create_user)
    BusinessRole.objects.create(project=hidden, user=create_user, role="PLATFORM_ADMIN", created_by=create_user)
    browser = APIClient()
    browser.force_authenticate(create_user)
    response = browser.get(f"/api/workspaces/{workspace.slug}/member-context/")
    assert response.status_code == 200
    row = response.data["members"][str(create_user.id)]
    assert row["business_roles"] == [{"project": "Visible", "role": "项目经理"}]
    assert row["identity_mapped"] is False
    assert response["Cache-Control"] == "no-store"


def test_member_context_denies_anonymous_and_nonadmins(workspace, create_user):
    endpoint = f"/api/workspaces/{workspace.slug}/member-context/"
    assert APIClient().get(endpoint).status_code in [401, 403]
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
    browser = APIClient()
    browser.force_authenticate(create_user)
    assert browser.get(endpoint).status_code == 403


def test_revoked_workspace_member_has_no_business_context(workspace, create_user):
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    browser = APIClient()
    browser.force_authenticate(create_user)
    assert browser.get(f"/api/workspaces/{workspace.slug}/member-context/").status_code == 403


def test_removed_project_member_is_not_shown_with_stale_business_role(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Revoked", identifier="MBR")
    ProjectMember.objects.create(project=project, member=create_user, role=20, is_active=False)
    BusinessRole.objects.create(project=project, user=create_user, role="PROJECT_MANAGER", created_by=create_user)
    browser = APIClient()
    browser.force_authenticate(create_user)
    response = browser.get(f"/api/workspaces/{workspace.slug}/member-context/")
    assert response.data["members"][str(create_user.id)]["business_roles"] == []


def test_member_context_uses_source_username_and_includes_additional_duties(workspace, create_user):
    from plane.quality.models import PlatformAccount

    project = Project.objects.create(workspace=workspace, name="Mixed", identifier="MIX")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    BusinessRole.objects.create(
        project=project,
        user=create_user,
        role="PROJECT_MANAGER",
        additional_roles=["TECHNICIAN"],
        created_by=create_user,
    )
    PlatformAccount.objects.create(
        user=create_user,
        source_instance="isolated",
        external_user_id=71,
        source_username="daq_operator",
        source_role="Collector",
    )
    browser = APIClient()
    browser.force_authenticate(create_user)
    response = browser.get(f"/api/workspaces/{workspace.slug}/member-context/")
    row = response.data["members"][str(create_user.id)]
    assert row["username"] == "daq_operator"
    assert {item["role"] for item in row["business_roles"]} == {"项目经理", "技术员"}


def test_admin_member_serializer_preserves_local_and_authority_usernames(create_user):
    from plane.app.serializers.user import UserAdminLiteSerializer
    from plane.quality.models import PlatformAccount

    assert UserAdminLiteSerializer(create_user).data["username"] == create_user.username
    PlatformAccount.objects.create(
        user=create_user,
        source_instance="isolated",
        external_user_id=72,
        source_username="source_account",
        source_role="Collector",
    )
    create_user.refresh_from_db()
    assert UserAdminLiteSerializer(create_user).data["username"] == "source_account"


def test_disabled_account_is_not_assignable_or_shown_as_active_project_member(workspace, create_user, session_client):
    from uuid import uuid4
    from plane.db.models import User

    project = Project.objects.create(workspace=workspace, name="Active accounts", identifier="ACT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    disabled = User.objects.create(
        username="disabled_" + uuid4().hex, email=uuid4().hex + "@local.test", is_active=False
    )
    WorkspaceMember.objects.create(workspace=workspace, member=disabled, role=15)
    ProjectMember.objects.create(project=project, member=disabled, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    context = session_client.get(base + "context/")
    assert str(disabled.id) not in {str(row["id"]) for row in context.data["members"]}
    response = session_client.post(
        base + "defects/", {"title": "Inactive assignee", "assignee_id": str(disabled.id)}, format="json"
    )
    assert response.status_code == 400


def test_member_serializer_reports_disabled_login_status(create_user):
    from plane.app.serializers.user import UserAdminLiteSerializer
    create_user.is_active = False
    create_user.save(update_fields=["is_active"])
    assert UserAdminLiteSerializer(create_user).data["is_active"] is False
