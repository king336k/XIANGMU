"""A project-scoped platform administrator includes manager duties without bypassing membership."""

import pytest
from plane.db.models import Project, ProjectMember, WorkspaceMember, State, Issue
from plane.quality.models import BusinessRole, ProjectRolePolicy

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def admin_scope(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="管理员业务权限", identifier="ADM161")
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, user=create_user, role="PLATFORM_ADMIN")
    State.objects.create(project=project, workspace=workspace, name="待处理", group="unstarted", default=True)
    return project, f"/api/workspaces/{workspace.slug}/projects/{project.id}/"


def test_admin_inherits_manager_native_and_quality_operations(session_client, admin_scope, create_user):
    project, base = admin_scope
    from plane.quality.permissions import ROLE_CAPABILITIES, capable, has_role

    assert has_role(project.id, create_user.id, "PROJECT_MANAGER")
    for role in ["PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER", "REPORTER"]:
        assert ROLE_CAPABILITIES[role] <= ROLE_CAPABILITIES["PLATFORM_ADMIN"]
        assert has_role(project.id, create_user.id, role)
    assert capable(project.id, create_user.id, "manage_test")
    created = session_client.post(base + "issues/", {"name": "管理员安排研发任务"}, format="json")
    assert created.status_code == 201, created.content
    issue_id = created.data["id"]
    policy = session_client.get(base + f"quality/native-issues/{issue_id}/policy/")
    assert policy.status_code == 200 and policy.data["can_arrange"] and policy.data["can_edit"]
    access = session_client.get("/api/quality-auth/work-access/")
    assert access.data["projects"][str(project.id)]["can_arrange"] is True
    case = session_client.post(
        base + "quality/cases/",
        {"title": "管理员管理测试用例", "steps": [{"action": "验证", "expected": "成功"}]},
        format="json",
    )
    assert case.status_code == 201, case.content
    defect = session_client.post(base + "quality/defects/", {"title": "管理员提报功能问题"}, format="json")
    assert defect.status_code == 201, defect.content
    url = base + f"quality/defects/{defect.data['id']}/"
    assert session_client.patch(url, {"status": "resolved", "fixed_build": "ui-v1"}, format="json").status_code == 200
    assert (
        session_client.patch(
            url,
            {"status": "closed", "verification_method": "manual", "verification_note": "按修复版本复查功能通过"},
            format="json",
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "boundary", ["project_readonly", "project_inactive", "workspace_readonly", "workspace_inactive"]
)
def test_admin_role_does_not_bypass_membership_boundaries(session_client, admin_scope, create_user, boundary):
    project, base = admin_scope
    if boundary.startswith("project"):
        ProjectMember.objects.filter(project=project, member=create_user).update(
            **({"role": 5} if boundary.endswith("readonly") else {"is_active": False})
        )
    else:
        WorkspaceMember.objects.filter(workspace=project.workspace, member=create_user).update(
            **({"role": 5} if boundary.endswith("readonly") else {"is_active": False})
        )
    denied = session_client.post(base + "quality/cases/", {"title": "不能越界", "steps": []}, format="json")
    assert denied.status_code in {403, 404}, denied.content
    access = session_client.get("/api/quality-auth/work-access/")
    assert str(project.id) not in access.data["projects"]
    assert session_client.post(base + "issues/", {"name": "不能绕过只读职责"}, format="json").status_code in {403, 404}


def test_global_admin_can_edit_projects_without_explicit_membership(
    session_client, admin_scope, create_user, workspace, mocker
):
    mocker.patch("plane.app.views.issue.base.issue_activity.delay")
    other = Project.objects.create(workspace=workspace, name="未加入项目", identifier="ADMOUT")
    issue = Issue.objects.create(project=other, workspace=workspace, name="不可跨项目管理")
    url = f"/api/workspaces/{workspace.slug}/projects/{other.id}/issues/{issue.id}/"
    assert session_client.patch(url, {"name": "管理员管理项目"}, format="json").status_code == 204
    issue.refresh_from_db()
    assert issue.name == "管理员管理项目"


@pytest.mark.parametrize("resource,model_name", [("cycles", "Cycle"), ("modules", "Module")])
def test_admin_manages_native_schedule_created_by_other_members(
    session_client, admin_scope, create_user, mocker, resource, model_name
):
    from plane.db import models

    project, base = admin_scope
    row = getattr(models, model_name).objects.create(
        project=project,
        workspace=project.workspace,
        name="其他成员安排",
        **({"owned_by": create_user} if model_name == "Cycle" else {}),
    )
    mocker.patch(f"plane.app.views.{resource[:-1]}.base.issue_activity.delay")
    result = session_client.delete(base + f"{resource}/{row.id}/")
    assert result.status_code in {200, 204}, result.content


def test_admin_executes_and_repairs_without_extra_assigned_role(session_client, admin_scope, create_user, mocker):
    from uuid import uuid4
    from plane.quality.models import Defect, TestPlan
    from plane.db.models import User

    project, base = admin_scope
    defect = Defect.objects.create(project=project, title="代处理问题")
    solution = session_client.post(
        base + "quality/solutions/",
        {
            "defect_id": str(defect.id),
            "title": "管理员处理",
            "root_cause": "错误分支",
            "steps": "修正分支",
            "verification": "验证功能",
        },
        format="json",
    )
    assert solution.status_code == 201, solution.content
    case = session_client.post(
        base + "quality/cases/",
        {
            "title": "管理员测试",
            "steps": [{"action": "操作", "expected": "通过"}],
        },
        format="json",
    ).data
    plan = session_client.post(
        base + "quality/plans/",
        {
            "name": "管理员代执行",
            "build": "v1",
            "environment": "隔离",
            "case_ids": [case["id"]],
            "managed": True,
        },
        format="json",
    ).data
    tester = User.objects.create(email="assigned-tester@admin.local", username="assigned-tester-admin161")
    TestPlan.objects.filter(pk=plan["id"]).update(status="ready", assignee=tester)
    claimed = session_client.post(
        base + f"quality/plans/{plan['id']}/workflow/",
        {
            "action": "claim",
            "expected_version": 1,
        },
        format="json",
    )
    assert claimed.status_code == 200, claimed.content
    assert str(claimed.data["assignee_id"]) == str(tester.id)
    executed = session_client.post(
        base + f"quality/items/{plan['items'][0]['id']}/executions/",
        {
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": "管理员实际验证通过",
        },
        format="json",
    )
    assert executed.status_code == 201, executed.content
    assert executed.data["created_by_id"] == str(create_user.id)
    after = TestPlan.objects.get(pk=plan["id"])
    assert after.assignee_id == tester.id


def test_admin_cannot_use_other_workspace_slug_to_bypass_project_scope(session_client, admin_scope, create_user):
    from plane.db.models import Workspace

    project, _ = admin_scope
    other = Workspace.objects.create(name="其他空间", slug="other-admin-scope", owner=create_user)
    WorkspaceMember.objects.create(workspace=other, member=create_user, role=15)
    WorkspaceMember.objects.filter(workspace=project.workspace, member=create_user).update(role=5)
    wrong_url = f"/api/workspaces/{other.slug}/projects/{project.id}/issues/"
    response = session_client.post(wrong_url, {"name": "不应写入另一个空间"}, format="json")
    assert response.status_code in {403, 404}, response.content
    assert not Issue.objects.filter(project=project, name="不应写入另一个空间").exists()


def test_admin_can_review_a_version_they_edited_or_submitted_with_own_audit(session_client, admin_scope, create_user):
    from plane.db.models import User
    from plane.quality.models import Defect, Solution, SolutionReview

    project, base = admin_scope
    author = User.objects.create(email="other-author@admin.local", username="other-author-admin161")
    defect = Defect.objects.create(project=project, title="管理员可自行复核", assignee=author)
    solution = Solution.objects.create(
        project=project,
        created_by=author,
        defect=defect,
        title="他人原方案",
        root_cause="原根因",
        steps="修复步骤",
        verification="验证结果",
    )
    url = base + f"quality/solutions/{solution.id}/"
    edited = session_client.patch(url, {"expected_version": 1, "root_cause": "管理员实际修改的根因"}, format="json")
    assert edited.status_code == 200, edited.content
    submitted = session_client.post(
        url + "submit/",
        {
            "expected_version": edited.data["edit_version"],
            "reviewer_ids": [str(create_user.id)],
            "required_count": 1,
        },
        format="json",
    )
    assert submitted.status_code == 200, submitted.content
    revision = submitted.data["revisions"][0]
    approved = session_client.post(
        url + "review/",
        {
            "revision_id": revision["id"],
            "decision": "approve",
        },
        format="json",
    )
    assert approved.status_code == 200 and approved.data["status"] == "approved", approved.content
    assert SolutionReview.objects.get(revision_id=revision["id"]).created_by_id == create_user.id
    solution.refresh_from_db()
    defect.refresh_from_db()
    assert solution.created_by_id == author.id and defect.assignee_id == author.id


def test_managed_admin_account_can_create_projects_without_becoming_instance_operator(admin_scope, create_user):
    from plane.quality.models import LocalManagedAccount
    from plane.quality.permissions import can_create_projects

    project, _ = admin_scope
    LocalManagedAccount.objects.create(user=create_user, created_by=create_user)
    assert can_create_projects(create_user) is True
    WorkspaceMember.objects.filter(workspace=project.workspace, member=create_user).update(is_active=False)
    assert can_create_projects(create_user) is False
