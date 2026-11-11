"""Personal actionable queue never substitutes project or business permissions."""

import pytest
from plane.db.models import Project, ProjectMember, Issue, IssueAssignee, State, User, WorkspaceMember
from plane.quality.models import (
    Defect,
    TestPlan,
    Solution,
    SolutionRevision,
    SolutionReview,
    BusinessRole,
    ProjectRolePolicy,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db]
URL = "/api/quality-auth/my-todos/"


@pytest.fixture
def todo_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="个人待办", identifier="TODO152")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


def test_personal_queue_combines_assigned_records_and_paginated_search(
    session_client, todo_project, create_user, workspace
):
    p = todo_project
    state = State.objects.create(project=p, workspace=workspace, name="处理中", group="started")
    issue = Issue.objects.create(project=p, workspace=workspace, name="研发待办", state=state)
    IssueAssignee.objects.create(project=p, workspace=workspace, issue=issue, assignee=create_user)
    defect = Defect.objects.create(project=p, title="缺陷待办", assignee=create_user)
    TestPlan.objects.create(
        project=p, name="测试待办", build="v1", environment="隔离", status="ready", assignee=create_user, managed=True
    )
    Defect.objects.create(project=p, title="无关缺陷")
    response = session_client.get(URL, {"workspace": workspace.slug, "per_page": 2})
    assert response.status_code == 200, response.content
    assert response.data["count"] == 3, response.data
    assert len(response.data["results"]) == 2 and response.data["next"]
    rows = session_client.get(URL, {"workspace": workspace.slug, "per_page": 20}).data["results"]
    assert {r["kind"] for r in rows} == {"task", "defect", "plan"}
    assert all(
        r["next_action"]
        and r["responsibility"]
        and r["url"].startswith((f"/{workspace.slug}/p/TODO152/", f"/{workspace.slug}/browse/TODO152-"))
        for r in rows
    )
    filtered = session_client.get(URL, {"workspace": workspace.slug, "kind": "defect", "search": defect.code})
    assert filtered.data["count"] == 1 and filtered.data["results"][0]["id"] == str(defect.id)


def test_queue_excludes_finished_inactive_and_unauthorized_projects(
    session_client, todo_project, create_user, workspace
):
    Defect.objects.create(project=todo_project, title="已完成", assignee=create_user, status="closed")
    hidden = Project.objects.create(workspace=workspace, name="未加入", identifier="HIDDEN152")
    Defect.objects.create(project=hidden, title="不能泄露", assignee=create_user)
    assert session_client.get(URL, {"workspace": workspace.slug}).data["count"] == 0
    Defect.objects.create(project=todo_project, title="曾分派", assignee=create_user)
    ProjectMember.objects.filter(project=todo_project).update(is_active=False)
    assert session_client.get(URL, {"workspace": workspace.slug}).data["count"] == 0


def test_queue_review_targets_only_current_unvoted_frozen_reviewer(
    session_client, todo_project, create_user, workspace
):
    author = User.objects.create(email="todo-author@local.test", username="todo-author")
    defect = Defect.objects.create(project=todo_project, title="待审缺陷")
    solution = Solution.objects.create(
        project=todo_project, defect=defect, title="待审方案", status="review", submitted_version=2, created_by=author
    )
    SolutionRevision.objects.create(
        project=todo_project,
        solution=solution,
        version=1,
        snapshot={},
        reviewer_ids=[str(create_user.id)],
        required_count=1,
    )
    revision = SolutionRevision.objects.create(
        project=todo_project,
        solution=solution,
        version=2,
        snapshot={},
        reviewer_ids=[str(create_user.id)],
        required_count=1,
    )
    result = session_client.get(URL, {"workspace": workspace.slug, "kind": "solution"})
    assert result.status_code == 200 and result.data["count"] == 1, result.content
    assert f"defect={defect.id}" in result.data["results"][0]["url"]
    SolutionReview.objects.create(project=todo_project, revision=revision, created_by=create_user, decision="approve")
    assert session_client.get(URL, {"workspace": workspace.slug, "kind": "solution"}).data["count"] == 0


def test_queue_strict_business_role_revocation_removes_actionable_records(
    session_client, todo_project, create_user, workspace
):
    ProjectRolePolicy.objects.create(project=todo_project, enabled=True)
    role = BusinessRole.objects.create(project=todo_project, user=create_user, role="TECHNICIAN")
    Defect.objects.create(project=todo_project, title="负责修复", assignee=create_user)
    TestPlan.objects.create(
        project=todo_project, name="错分测试", build="1", environment="x", status="ready", assignee=create_user
    )
    assert session_client.get(URL, {"workspace": workspace.slug}).data["count"] == 1
    role.role = "REPORTER"
    role.save()
    assert session_client.get(URL, {"workspace": workspace.slug}).data["count"] == 0


def test_queue_requires_workspace_membership_and_rejects_invalid_filters(
    session_client, todo_project, workspace, create_user, api_client
):
    from rest_framework.test import APIClient

    assert APIClient().get(URL, {"workspace": workspace.slug}).status_code == 401
    assert session_client.get(URL, {"workspace": workspace.slug, "kind": "invalid"}).status_code == 400
    assert session_client.get(URL, {"workspace": workspace.slug, "per_page": 1000}).status_code == 400
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    assert session_client.get(URL, {"workspace": workspace.slug}).status_code == 403


def test_queue_requirement_link_targets_uuid_and_code_is_requirement_number(
    session_client, todo_project, create_user, workspace
):
    from plane.quality.models import Requirement

    issue = Issue.objects.create(project=todo_project, workspace=workspace, name="待开发需求")
    IssueAssignee.objects.create(project=todo_project, workspace=workspace, issue=issue, assignee=create_user)
    Requirement.objects.create(project=todo_project, issue=issue, number=1)
    result = session_client.get(URL, {"workspace": workspace.slug, "kind": "requirement"})
    assert result.status_code == 200 and result.data["count"] == 1, result.content
    row = result.data["results"][0]
    assert row["code"] == "TODO152-R-1"
    assert row["url"].endswith(f"requirements/?requirement={issue.id}")


def test_queue_high_volume_paging_and_additional_duty(session_client, todo_project, create_user, workspace):
    ProjectRolePolicy.objects.create(project=todo_project, enabled=True)
    role = BusinessRole.objects.create(
        project=todo_project, user=create_user, role="REPORTER", additional_roles=["TECHNICIAN"]
    )
    for index in range(23):
        Defect.objects.create(project=todo_project, title=f"故障{index}", assignee=create_user)
    response = session_client.get(URL, {"workspace": workspace.slug, "page": 2, "per_page": 20})
    assert response.status_code == 200 and response.data["count"] == 23 and len(response.data["results"]) == 3, (
        response.content
    )
    role.additional_roles = []
    role.save()
    assert session_client.get(URL, {"workspace": workspace.slug}).data["count"] == 0


def test_queue_ordinary_plan_only_pending_cases_and_direct_execution_label(session_client,todo_project,create_user,workspace):
    from uuid import uuid4
    from plane.quality.models import TestCase, PlanItem, TestExecution
    from plane.quality.views import add_revision
    plan=TestPlan.objects.create(project=todo_project,name="普通执行",build="1",environment="x",assignee=create_user)
    case=TestCase.objects.create(project=todo_project,title="待执行用例",steps=[{"action":"检查","expected":"正常"}])
    item=PlanItem.objects.create(project=todo_project,plan=plan,case=case,revision=add_revision(case,create_user))
    response=session_client.get(URL,{"workspace":workspace.slug,"kind":"plan"})
    assert response.data["count"]==1 and response.data["results"][0]["next_action"]=="记录结果",response.content
    TestExecution.objects.create(project=todo_project,item=item,request_id=uuid4(),round_no=1,result="failed")
    assert session_client.get(URL,{"workspace":workspace.slug,"kind":"plan"}).data["count"]==0
    plan.round_no = 2; plan.save()
    # Ordinary plans do not use the managed return workflow; any-round latest execution remains complete.
    assert session_client.get(URL,{"workspace":workspace.slug,"kind":"plan"}).data["count"]==0


def test_queue_with_active_regression_does_not_send_technician_to_duplicate_application(session_client,todo_project,create_user,workspace):
    from uuid import uuid4
    from plane.quality.models import DataRegression, Solution, SolutionRevision, DaqBinding
    defect=Defect.objects.create(project=todo_project,title="修复待回归",status="resolved",assignee=create_user)
    issue=Issue.objects.create(project=todo_project,workspace=workspace,name="来源任务")
    binding=DaqBinding.objects.create(project=todo_project,issue=issue,source_instance="source",platform_task_id=1,source_record_id="source-session")
    solution=Solution.objects.create(project=todo_project,defect=defect,title="冻结方案")
    revision=SolutionRevision.objects.create(project=todo_project,solution=solution,version=1,snapshot={},reviewer_ids=[],required_count=1)
    plan=TestPlan.objects.create(project=todo_project,name="已送回归",build="1",environment="x",managed=True,status="running")
    from django.utils import timezone
    DataRegression.objects.create(project=todo_project,plan=plan,defect=defect,solution_revision=revision,binding=binding,fixed_build="1",resolved_at=timezone.now(),round_started_at=timezone.now())
    response=session_client.get(URL,{"workspace":workspace.slug,"kind":"defect"})
    assert response.data["count"]==0,response.content


def test_queue_uses_requirement_business_state_and_excludes_retired_requirements(session_client,todo_project,create_user,workspace):
    from plane.quality.models import Requirement
    for status in ["cancelled","archived","completed","approved"]:
        issue=Issue.objects.create(project=todo_project,workspace=workspace,name=status)
        IssueAssignee.objects.create(project=todo_project,workspace=workspace,issue=issue,assignee=create_user)
        Requirement.objects.create(project=todo_project,issue=issue,status=status)
    response=session_client.get(URL,{"workspace":workspace.slug,"kind":"requirement"})
    assert response.data["count"]==1,response.content
    assert response.data["results"][0]["status"]=="approved"


def test_readonly_workspace_member_has_empty_action_queue_instead_of_home_error(
    session_client, todo_project, create_user, workspace
):
    """Readonly members can open home, but stale assignment must not grant work."""
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(role=5)
    Defect.objects.create(project=todo_project, title="只读成员不能处理", assignee=create_user)
    response = session_client.get(URL, {"workspace": workspace.slug})
    assert response.status_code == 200, response.content
    assert response.data["count"] == 0
    assert response.data["results"] == []
