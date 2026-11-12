"""Exercise actual settings routes, including roles hidden by UI controls."""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient
from django.utils import timezone
from plane.db.models import Project, ProjectMember, WorkspaceMember, State, User, Label, Estimate
from plane.license.models import Instance, InstanceAdmin
from plane.quality.models import BusinessRole, ProjectRolePolicy

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def settings_scope(workspace):
    user = User.objects.create(username="settings-audit", email="settings-audit@test.invalid")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
    project = Project.objects.create(workspace=workspace, name="权限验收", identifier="ROLEAUD")
    ProjectMember.objects.create(project=project, member=user, role=15)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    instance = Instance.objects.create(
        instance_name="audit", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    client = APIClient()
    client.force_authenticate(user=user)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/"
    return client, user, project, instance, base


def test_canonical_admin_native_member_manages_states(settings_scope):
    client, user, project, instance, base = settings_scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    state = client.post(
        base + "states/", {"name": "管理员新增状态", "group": "started", "color": "#123456"}, format="json"
    )
    assert state.status_code == 200, state.content
    state_url = base + f"states/{state.data['id']}/"
    assert client.patch(state_url, {"name": "管理员重命名状态"}, format="json").status_code == 200
    assert client.delete(state_url).status_code == 204


def test_canonical_admin_native_member_manages_labels(settings_scope):
    client, user, project, instance, base = settings_scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    label = client.post(base + "issue-labels/", {"name": "管理员标签", "color": "#123456"}, format="json")
    assert label.status_code == 201, label.content
    label_url = base + f"issue-labels/{label.data['id']}/"
    assert client.patch(label_url, {"name": "管理员重命名标签"}, format="json").status_code == 200
    assert client.delete(label_url).status_code == 204


@pytest.mark.parametrize("role", ["PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER", "guest"])
def test_ordinary_roles_cannot_mutate_project_configuration(settings_scope, role):
    client, user, project, _, base = settings_scope
    if role == "guest":
        ProjectMember.objects.filter(project=project, member=user).update(role=5)
    else:
        BusinessRole.objects.create(project=project, user=user, role=role)
    state = State.objects.create(project=project, workspace=project.workspace, name="现有状态", group="started")
    response = client.patch(base + f"states/{state.id}/", {"name": "不应修改"}, format="json")
    assert response.status_code == 403, response.content
    state.refresh_from_db()
    assert state.name == "现有状态"


@pytest.mark.parametrize("boundary", ["workspace_inactive", "project_inactive", "workspace_guest", "project_guest"])
def test_former_admin_settings_require_live_writable_scope(settings_scope, boundary):
    client, user, project, instance, base = settings_scope
    # No global grant: scope boundaries still constrain ordinary and former admins.
    model = WorkspaceMember if boundary.startswith("workspace") else ProjectMember
    filters = (
        {"member": user, "workspace": project.workspace}
        if model is WorkspaceMember
        else {"member": user, "project": project}
    )
    model.objects.filter(**filters).update(**({"is_active": False} if boundary.endswith("inactive") else {"role": 5}))
    response = client.post(base + "states/", {"name": "越界状态", "group": "started"}, format="json")
    assert response.status_code in {403, 404}, response.content
    assert not State.objects.filter(project=project, name="越界状态").exists()


@pytest.mark.parametrize("role", ["TECHNICIAN", "REGRESSION_TESTER", "REPORTER", "guest"])
@pytest.mark.parametrize("resource", ["labels", "estimates"])
def test_ordinary_roles_cannot_update_settings_by_put_or_patch(settings_scope, role, resource):
    client, user, project, _, base = settings_scope
    if role == "guest":
        ProjectMember.objects.filter(project=project, member=user).update(role=5)
    else:
        BusinessRole.objects.create(project=project, user=user, role=role)
    if resource == "labels":
        obj = Label.objects.create(project=project, workspace=project.workspace, name="原始标签")
        response = client.put(base + f"issue-labels/{obj.id}/", {"name": "越权标签"}, format="json")
    else:
        obj = Estimate.objects.create(project=project, workspace=project.workspace, name="原始估点")
        response = client.delete(base + f"estimates/{obj.id}/")
    assert response.status_code == 403, response.content
    assert type(obj).objects.filter(pk=obj.pk).exists()


def test_canonical_admin_can_delete_public_project_document(settings_scope):
    from plane.db.models import Page, ProjectPage

    client, user, project, instance, base = settings_scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    author = User.objects.create(username="document-author", email="author@test.invalid")
    page = Page.objects.create(
        workspace=project.workspace,
        name="可管理文档",
        owned_by=author,
        access=Page.PUBLIC_ACCESS,
        archived_at=timezone.now(),
    )
    ProjectPage.objects.create(workspace=project.workspace, project=project, page=page)
    response = client.delete(base + f"pages/{page.id}/")
    assert response.status_code in {200, 204}, response.content
    assert not Page.objects.filter(pk=page.pk).exists()


@pytest.mark.parametrize("action", ["archive", "lock"])
@pytest.mark.parametrize("administrator", [True, False])
def test_document_management_matches_effective_admin_authority(settings_scope, action, administrator):
    from plane.db.models import Page, ProjectPage

    client, user, project, instance, base = settings_scope
    if administrator:
        InstanceAdmin.objects.create(instance=instance, user=user)
    else:
        BusinessRole.objects.create(project=project, user=user, role="TECHNICIAN")
    author = User.objects.create(username="page-owner", email="page-owner@test.invalid")
    page = Page.objects.create(workspace=project.workspace, name="管理文档", owned_by=author, access=Page.PUBLIC_ACCESS)
    ProjectPage.objects.create(workspace=project.workspace, project=project, page=page)
    detail = client.get(base + f"pages/{page.id}/")
    assert detail.status_code == 200, detail.content
    response = client.post(base + f"pages/{page.id}/{action}/", {}, format="json")
    expected_status = (200 if action == "archive" else 204) if administrator else 403
    assert response.status_code == expected_status, response.content
    assert detail.data.get("can_manage") is administrator


def test_canonical_admin_native_member_can_inspect_workspace_member_context(settings_scope):
    client, user, project, instance, _ = settings_scope
    InstanceAdmin.objects.create(instance=instance, user=user)
    response = client.get(f"/api/workspaces/{project.workspace.slug}/member-context/")
    assert response.status_code == 200, response.content
    assert str(user.id) in response.data["members"]


@pytest.mark.parametrize("resource", ["states", "labels"])
def test_personal_api_key_cannot_bypass_strict_settings_permissions(settings_scope, resource):
    from plane.db.models.api import APIToken

    client, user, project, _, _ = settings_scope
    BusinessRole.objects.create(project=project, user=user, role="TECHNICIAN")
    token = APIToken.objects.create(user=user, label="audit", token="isolated-role-audit-api-token")
    client.force_authenticate(user=None)
    client.credentials(HTTP_X_API_KEY=token.token)
    response = client.post(
        f"/api/v1/workspaces/{project.workspace.slug}/projects/{project.id}/{resource}/",
        {"name": "不应创建", "group": "started", "color": "#123456"},
        format="json",
    )
    assert response.status_code == 403, response.content
