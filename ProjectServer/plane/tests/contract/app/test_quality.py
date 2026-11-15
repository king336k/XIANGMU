"""Contract tests for the native quality workbench; uses pytest's isolated test DB."""

from uuid import uuid4

import pytest
from plane.db.models import Project, ProjectMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def quality_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="质量项目", identifier="QA")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project


def endpoint(project, path):
    return f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/{path}"


def make_case(client, project, title="登录验证"):
    response = client.post(
        endpoint(project, "cases/"),
        {
            "title": title,
            "module": "账号",
            "preconditions": "已有账号",
            "steps": [{"action": "输入账号密码", "expected": "进入首页"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.data


def make_plan(client, project, case):
    response = client.post(
        endpoint(project, "plans/"),
        {
            "name": "首轮测试",
            "build": "v1",
            "environment": "本地",
            "case_ids": [case["id"]],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.data


def execute(client, project, plan, result="failed", **extra):
    return client.post(
        endpoint(project, f"items/{plan['items'][0]['id']}/executions/"),
        {
            "request_id": str(uuid4()),
            "result": result,
            "actual_result": "实际结果",
            **extra,
        },
        format="json",
    )


def test_case_revision_does_not_rewrite_plan(session_client, quality_project):
    case = make_case(session_client, quality_project)
    plan = make_plan(session_client, quality_project, case)
    response = session_client.patch(
        endpoint(quality_project, f"cases/{case['id']}/"),
        {
            "title": "修改后的标题",
            "expected_version": 1,
            "steps": [{"action": "新步骤", "expected": "新预期"}],
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["version"] == 2
    original = session_client.get(endpoint(quality_project, f"plans/{plan['id']}/")).data
    assert original["items"][0]["revision"]["title"] == "登录验证"
    assert original["items"][0]["revision"]["version"] == 1
    stale = session_client.patch(
        endpoint(quality_project, f"cases/{case['id']}/"),
        {
            "title": "覆盖",
            "expected_version": 1,
        },
        format="json",
    )
    assert stale.status_code == 409


def test_execution_is_append_only_and_retry_is_idempotent(session_client, quality_project):
    plan = make_plan(session_client, quality_project, make_case(session_client, quality_project))
    request_id = str(uuid4())
    first = execute(session_client, quality_project, plan, request_id=request_id)
    assert first.status_code == 201
    retry = execute(session_client, quality_project, plan, request_id=request_id)
    assert retry.status_code == 200
    assert retry.data["id"] == first.data["id"]
    conflict = execute(session_client, quality_project, plan, result="passed", request_id=request_id)
    assert conflict.status_code == 409
    assert execute(session_client, quality_project, plan, result="passed").status_code == 201
    history = session_client.get(endpoint(quality_project, f"items/{plan['items'][0]['id']}/executions/"))
    assert history.data["count"] == 2
    report = session_client.get(endpoint(quality_project, f"plans/{plan['id']}/")).data["summary"]
    assert report["passed"] == 1 and report["failed"] == 0 and report["total"] == 1


def test_defect_requires_new_matching_regression_before_close(session_client, quality_project):
    case = make_case(session_client, quality_project)
    plan = make_plan(session_client, quality_project, case)
    failed = execute(session_client, quality_project, plan).data
    defect_url = endpoint(quality_project, f"executions/{failed['id']}/defect/")
    response = session_client.post(defect_url, {"severity": "major"}, format="json")
    assert response.status_code == 201, response.content
    defect = response.data
    retry = session_client.post(defect_url, {"severity": "major"}, format="json")
    assert retry.status_code == 200 and retry.data["id"] == defect["id"]
    url = endpoint(quality_project, f"defects/{defect['id']}/")
    assert session_client.patch(url, {"status": "closed"}, format="json").status_code == 409
    early = execute(session_client, quality_project, plan, result="passed").data
    assert session_client.patch(url, {"status": "resolved", "fixed_build": "v2"}, format="json").status_code == 200
    assert (
        session_client.patch(
            url, {"status": "closed", "regression_execution_id": early["id"]}, format="json"
        ).status_code
        == 409
    )
    other = make_plan(session_client, quality_project, make_case(session_client, quality_project, "其他用例"))
    wrong = execute(session_client, quality_project, other, result="passed").data
    assert (
        session_client.patch(
            url, {"status": "closed", "regression_execution_id": wrong["id"]}, format="json"
        ).status_code
        == 409
    )
    regression_plan = make_plan(session_client, quality_project, case)
    from plane.quality.models import TestPlan

    TestPlan.objects.filter(id=regression_plan["id"]).update(build="v2")
    regression = execute(session_client, quality_project, regression_plan, result="passed").data
    closed = session_client.patch(url, {"status": "closed", "regression_execution_id": regression["id"]}, format="json")
    assert closed.status_code == 409, closed.content
    assert session_client.patch(url, {"status": "open"}, format="json").status_code == 200


def test_quality_requires_active_membership_and_guest_cannot_write(session_client, quality_project, create_user):
    from plane.db.models import WorkspaceMember

    case = make_case(session_client, quality_project)
    member = ProjectMember.objects.get(project=quality_project, member=create_user)
    member.role = 5
    member.save()
    assert session_client.get(endpoint(quality_project, "cases/")).status_code == 200
    assert (
        session_client.patch(
            endpoint(quality_project, f"cases/{case['id']}/"), {"expected_version": 1, "title": "越权"}, format="json"
        ).status_code
        == 403
    )
    member.is_active = False
    member.save()
    assert session_client.get(endpoint(quality_project, "cases/")).status_code == 403
    member.is_active = True
    member.save()
    WorkspaceMember.objects.filter(workspace=quality_project.workspace, member=create_user).update(is_active=False)
    assert session_client.get(endpoint(quality_project, "cases/")).status_code == 403


def test_cross_project_links_and_unknown_ids_rejected(session_client, quality_project, workspace, create_user):
    from plane.db.models import Issue

    other = Project.objects.create(workspace=workspace, name="另一个项目", identifier="OTHER")
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    foreign_case = make_case(session_client, other)
    r = session_client.post(
        endpoint(quality_project, "plans/"),
        {
            "name": "越界",
            "build": "v1",
            "environment": "本地",
            "case_ids": [foreign_case["id"]],
        },
        format="json",
    )
    assert r.status_code == 400
    issue = Issue.objects.create(project=other, name="跨项目需求")
    r = session_client.post(
        endpoint(quality_project, "cases/"),
        {
            "title": "越界",
            "steps": [{"action": "步骤", "expected": "预期"}],
            "requirement_id": str(issue.id),
        },
        format="json",
    )
    assert r.status_code == 400
    assert session_client.get(endpoint(quality_project, f"cases/{uuid4()}/")).status_code == 404


def test_invalid_steps_and_empty_plan_are_rejected(session_client, quality_project):
    r = session_client.post(endpoint(quality_project, "cases/"), {"title": "空步骤", "steps": []}, format="json")
    assert r.status_code == 400
    r = session_client.post(
        endpoint(quality_project, "plans/"),
        {"name": "空计划", "build": "v1", "environment": "本地", "case_ids": []},
        format="json",
    )
    assert r.status_code == 400


def test_quality_anonymous_denied(api_client, quality_project):
    assert api_client.get(endpoint(quality_project, "cases/")).status_code in (401, 403)


def test_manual_defect_and_repair_task_do_not_auto_close(session_client, quality_project):
    from plane.db.models import Issue

    case = make_case(session_client, quality_project)
    task = Issue.objects.create(project=quality_project, name="修复任务")
    response = session_client.post(
        endpoint(quality_project, "defects/"),
        {
            "title": "独立提交的缺陷",
            "case_id": case["id"],
            "severity": "critical",
            "affected_build": "v1",
            "description": "重现步骤",
            "repair_issue_id": str(task.id),
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    defect = response.data
    assert defect["repair_issue_id"] == str(task.id)
    url = endpoint(quality_project, f"defects/{defect['id']}/")
    assert session_client.patch(url, {"status": "resolved", "fixed_build": "v2"}, format="json").status_code == 200
    plan = make_plan(session_client, quality_project, case)
    old_build = execute(session_client, quality_project, plan, "passed").data
    assert (
        session_client.patch(
            url, {"status": "closed", "regression_execution_id": old_build["id"]}, format="json"
        ).status_code
        == 409
    )


def test_same_version_new_result_cannot_close_resolved_defect(session_client, quality_project):
    case = make_case(session_client, quality_project)
    plan = make_plan(session_client, quality_project, case)
    failed = execute(session_client, quality_project, plan).data
    defect = session_client.post(
        endpoint(quality_project, f"executions/{failed['id']}/defect/"), {}, format="json"
    ).data
    url = endpoint(quality_project, f"defects/{defect['id']}/")
    assert session_client.patch(url, {"status": "resolved", "fixed_build": "v2"}, format="json").status_code == 200
    passed = execute(session_client, quality_project, plan, "passed").data
    assert (
        session_client.patch(
            url, {"status": "closed", "regression_execution_id": passed["id"]}, format="json"
        ).status_code
        == 409
    )


def test_report_counts_latest_results_with_explicit_denominators(session_client, quality_project):
    case = make_case(session_client, quality_project)
    plan = make_plan(session_client, quality_project, case)
    execute(session_client, quality_project, plan, "failed")
    execute(session_client, quality_project, plan, "passed")
    r = session_client.get(endpoint(quality_project, "report/"))
    assert r.status_code == 200
    assert r.data["summary"]["total"] == 1
    assert r.data["summary"]["passed"] == 1
    assert r.data["summary"]["execution_rate"] == 100
    assert r.data["summary"]["pass_rate"] == 100


def test_close_cannot_change_fixed_build_without_matching_regression(session_client, quality_project):
    case = make_case(session_client, quality_project)
    plan = make_plan(session_client, quality_project, case)
    failed = execute(session_client, quality_project, plan).data
    defect = session_client.post(
        endpoint(quality_project, f"executions/{failed['id']}/defect/"), {}, format="json"
    ).data
    url = endpoint(quality_project, f"defects/{defect['id']}/")
    session_client.patch(url, {"status": "resolved", "fixed_build": "v1"}, format="json")
    passed = execute(session_client, quality_project, plan, "passed").data
    response = session_client.patch(
        url, {"status": "closed", "fixed_build": "untested", "regression_execution_id": passed["id"]}, format="json"
    )
    assert response.status_code == 409


def test_unknown_regression_is_not_found_not_server_error(session_client, quality_project):
    case = make_case(session_client, quality_project)
    plan = make_plan(session_client, quality_project, case)
    failed = execute(session_client, quality_project, plan).data
    defect = session_client.post(
        endpoint(quality_project, f"executions/{failed['id']}/defect/"), {}, format="json"
    ).data
    url = endpoint(quality_project, f"defects/{defect['id']}/")
    session_client.patch(url, {"status": "resolved", "fixed_build": "v2"}, format="json")
    response = session_client.patch(url, {"status": "closed", "regression_execution_id": str(uuid4())}, format="json")
    assert response.status_code == 409


def test_workspace_guest_does_not_get_write_controls(session_client, quality_project, create_user):
    from plane.db.models import WorkspaceMember

    WorkspaceMember.objects.filter(workspace=quality_project.workspace, member=create_user).update(role=5)
    response = session_client.get(endpoint(quality_project, "context/"))
    assert response.status_code == 200
    assert response.data["can_write"] is False
    response = session_client.post(
        endpoint(quality_project, "cases/"),
        {"title": "越权", "steps": [{"action": "步骤", "expected": "预期"}]},
        format="json",
    )
    assert response.status_code == 403
