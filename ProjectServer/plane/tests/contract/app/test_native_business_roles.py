"""Strict business duties apply to native Plane issue entry points too."""

import pytest
from plane.db.models import Project, ProjectMember, Issue, IssueAssignee, State
from plane.quality.models import BusinessRole, ProjectRolePolicy

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def native_roles(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="原生业务职责", identifier="NBR")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    role = BusinessRole.objects.create(project=project, user=create_user, role="PROJECT_MANAGER")
    issue = Issue.objects.create(project=project, workspace=workspace, name="研发修复任务")
    done = State.objects.create(project=project, workspace=workspace, name="完成", group="completed")
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/", project, issue, done, role


@pytest.mark.parametrize("role_name", ["REPORTER", "REGRESSION_TESTER"])
def test_non_development_roles_cannot_mutate_native_workflow_or_assignments(
    session_client, native_roles, role_name, create_user
):
    base, project, issue, done, role = native_roles
    role.role = role_name
    role.save()
    response = session_client.patch(
        base + f"issues/{issue.id}/", {"state_id": str(done.id), "assignee_ids": [str(create_user.id)]}, format="json"
    )
    assert response.status_code == 403, response.content
    assert session_client.post(base + "issues/", {"name": "越权创建研发任务"}, format="json").status_code == 403
    assert session_client.delete(base + f"issues/{issue.id}/").status_code == 403
    issue.refresh_from_db()
    assert issue.state_id != done.id


def test_technician_updates_own_work_but_cannot_take_over_other_assignments(session_client, native_roles, create_user):
    base, project, issue, done, role = native_roles
    role.role = "TECHNICIAN"
    role.save()
    assert (
        session_client.patch(base + f"issues/{issue.id}/", {"state_id": str(done.id)}, format="json").status_code == 403
    )
    IssueAssignee.objects.create(project=project, workspace=project.workspace, issue=issue, assignee=create_user)
    response = session_client.patch(base + f"issues/{issue.id}/", {"state_id": str(done.id)}, format="json")
    assert response.status_code in [200, 204], response.content
    assert session_client.patch(base + f"issues/{issue.id}/", {"assignee_ids": []}, format="json").status_code == 403


def test_manager_can_arrange_native_work_and_non_strict_projects_keep_original_behavior(session_client, native_roles):
    base, project, issue, done, role = native_roles
    assert session_client.patch(
        base + f"issues/{issue.id}/", {"state_id": str(done.id)}, format="json"
    ).status_code in [200, 204]
    ProjectRolePolicy.objects.filter(project=project).update(enabled=False)
    role.role = "REPORTER"
    role.save()
    assert session_client.post(base + "issues/", {"name": "普通项目原有操作"}, format="json").status_code == 201


def test_external_api_key_cannot_bypass_strict_native_roles(api_key_client, native_roles, workspace):
    base, project, issue, done, role = native_roles
    role.role = "REPORTER"
    role.save()
    url = f"/api/v1/workspaces/{workspace.slug}/projects/{project.id}/issues/{issue.id}/"
    response = api_key_client.patch(url, {"state": str(done.id)}, format="json")
    assert response.status_code == 403, response.content
    assert api_key_client.delete(url).status_code == 403


def test_private_draft_conversion_cannot_bypass_business_creation_scope(
    session_client, native_roles, create_user, workspace
):
    from plane.db.models import DraftIssue

    base, project, issue, done, role = native_roles
    role.role = "REPORTER"
    role.save()
    draft = DraftIssue.objects.create(workspace=workspace, project=project, created_by=create_user, name="个人草稿")
    DraftIssue.objects.filter(pk=draft.pk).update(created_by=create_user)
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/draft-to-issue/{draft.id}/", {"name": "草稿越权发布"}, format="json"
    )
    assert response.status_code == 403, response.content


def test_native_ui_policy_matches_server_role_and_requirement_content_rules(session_client, native_roles, create_user):
    base, project, issue, done, role = native_roles
    url = base + f"quality/native-issues/{issue.id}/policy/"
    role.role = "REPORTER"
    role.save()
    response = session_client.get(url)
    assert response.status_code == 200, response.content
    assert not response.data["can_edit"] and not response.data["can_arrange"]
    role.role = "TECHNICIAN"
    role.save()
    IssueAssignee.objects.create(project=project, workspace=project.workspace, issue=issue, assignee=create_user)
    response = session_client.get(url)
    assert response.data["can_edit"] and not response.data["can_arrange"]


def test_native_work_item_access_reports_business_scope(session_client, native_roles):
    base, project, issue, done, binding = native_roles
    for role, arrange, edit in [
        ("REPORTER", False, False),
        ("REGRESSION_TESTER", False, False),
        ("TECHNICIAN", False, True),
        ("PROJECT_MANAGER", True, True),
    ]:
        binding.role = role
        binding.save()
        response = session_client.get("/api/quality-auth/work-access/")
        assert response.status_code == 200, response.content
        row = response.data["projects"][str(project.id)]
        assert row["can_arrange"] is arrange and row["can_edit"] is edit
        assert row["own_only"] is (role == "TECHNICIAN")


@pytest.mark.parametrize("role_name", ["REPORTER", "REGRESSION_TESTER", "TECHNICIAN"])
@pytest.mark.parametrize("resource", ["cycles", "modules"])
def test_native_schedule_creation_cannot_bypass_project_manager_duty(session_client, native_roles, role_name, resource):
    base, project, issue, done, binding = native_roles
    binding.role = role_name
    binding.save()
    result = session_client.post(base + resource + "/", {"name": "越权变更研发排期"}, format="json")
    assert result.status_code == 403, result.content


@pytest.mark.parametrize("resource", ["cycles/", "modules/", "issues/", "pages/", "states/", "members/"])
def test_removed_workspace_member_cannot_read_native_project_content(
    session_client, native_roles, create_user, workspace, resource
):
    from plane.db.models import WorkspaceMember

    base, project, issue, done, binding = native_roles
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    response = session_client.get(base + resource)
    assert response.status_code == 403, response.content


@pytest.mark.parametrize("restriction", ["reporter", "guest_owner", "workspace_guest_owner"])
@pytest.mark.parametrize("action", ["create", "title", "description", "duplicate"])
def test_page_content_respects_business_duty_and_owner_downgrade(
    session_client, native_roles, create_user, workspace, restriction, action
):
    from plane.db.models import WorkspaceMember, Page, ProjectPage

    base, project, issue, done, binding = native_roles
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    binding.role = "REPORTER" if restriction == "reporter" else "TECHNICIAN"
    binding.save()
    if restriction == "guest_owner":
        ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    elif restriction == "workspace_guest_owner":
        WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
    page = Page.objects.create(
        workspace=workspace, name="原本人创建的文档", owned_by=create_user, access=Page.PUBLIC_ACCESS
    )
    ProjectPage.objects.create(project=project, workspace=workspace, page=page)
    if action == "create":
        response = session_client.post(base + "pages/", {"name": "越权创建文档"}, format="json")
    elif action == "title":
        response = session_client.patch(base + f"pages/{page.id}/", {"name": "越权改名"}, format="json")
    elif action == "description":
        response = session_client.patch(
            base + f"pages/{page.id}/description/", {"description_html": "<p>越权修改内容</p>"}, format="json"
        )
    else:
        response = session_client.post(base + f"pages/{page.id}/duplicate/", {}, format="json")
    assert response.status_code == 403, response.content
    page.refresh_from_db()
    assert page.name == "原本人创建的文档"


@pytest.mark.parametrize(
    "role_name", ["PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER"]
)
def test_page_server_flags_match_editable_content_and_private_visibility(
    session_client, native_roles, create_user, workspace, role_name
):
    from plane.db.models import WorkspaceMember, Page, ProjectPage, User

    base, project, issue, done, binding = native_roles
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=15)
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    binding.role = role_name
    binding.save()
    public_page = Page.objects.create(
        workspace=workspace, name="共享文档", owned_by=create_user, access=Page.PUBLIC_ACCESS
    )
    owner = User.objects.create(username="private-doc-owner", email="private-doc-owner@example.invalid")
    private_page = Page.objects.create(
        workspace=workspace, name="他人私有文档", owned_by=owner, access=Page.PRIVATE_ACCESS
    )
    for page in [public_page, private_page]:
        ProjectPage.objects.create(project=project, workspace=workspace, page=page)
    response = session_client.get(base + f"pages/{public_page.id}/")
    assert response.status_code == 200, response.content
    writable = role_name != "REPORTER"
    assert response.data["can_write"] is writable
    access = session_client.get("/api/quality-auth/work-access/")
    assert access.data["projects"][str(project.id)]["can_edit_documents"] is writable
    assert session_client.get(base + f"pages/{private_page.id}/").status_code == 403
    assert session_client.get(base + f"pages/{private_page.id}/description/").status_code == 403
    assert str(private_page.id) not in str(session_client.get(base + "pages/").data)
    if writable:
        updated = session_client.patch(base + f"pages/{public_page.id}/", {"name": "合法更新"}, format="json")
        assert updated.status_code == 200, updated.content
        assert updated.data["can_write"] is True
