"""Testers own test assets and scheduling; project acceptance stays with managers."""

from uuid import uuid4
import pytest
from plane.db.models import User, Project, ProjectMember, WorkspaceMember
from plane.quality.models import BusinessRole, ProjectRolePolicy, TestExecution, PlanEvent, QualityLifecycleEvent
from plane.quality.permissions import capable
from plane.license.models import Instance
from django.utils import timezone

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def tester_scope(session_client, workspace, create_user):
    Instance.objects.create(
        instance_name="测试职责", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    project = Project.objects.create(workspace=workspace, name="测试员完整职责", identifier="TESTER")
    ProjectMember.objects.create(project=project, member=create_user, role=15)
    BusinessRole.objects.create(project=project, user=create_user, role="REGRESSION_TESTER")
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    manager = User.objects.create(email="planmanager@tester.invalid", username="planmanager")
    WorkspaceMember.objects.create(workspace=workspace, member=manager, role=15)
    ProjectMember.objects.create(project=project, member=manager, role=15)
    BusinessRole.objects.create(project=project, user=manager, role="PROJECT_MANAGER")
    return project, create_user, manager, f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"


def test_tester_can_manage_case_suite_resources_and_plan_then_manager_accepts(session_client, tester_scope):
    project, tester, manager, base = tester_scope
    assert capable(project.id, tester.id, "manage_case")
    assert capable(project.id, tester.id, "manage_test_plan")
    case = session_client.post(
        base + "cases/", {"title": "测试员编写", "steps": [{"action": "运行", "expected": "通过"}]}, format="json"
    )
    assert case.status_code == 201, case.data
    cid = case.data["id"]
    edited = session_client.patch(base + f"cases/{cid}/", {"expected_version": 1, "title": "测试员维护"}, format="json")
    assert edited.status_code == 200
    suite = session_client.post(base + "suites/", {"name": "测试套件", "case_ids": [cid]}, format="json")
    assert suite.status_code == 201, suite.data
    sid = suite.data["id"]
    assert (
        session_client.patch(
            base + f"suites/{sid}/", {"expected_version": 1, "description": "测试员维护套件"}, format="json"
        ).status_code
        == 200
    )
    assert (
        session_client.post(
            base + f"suites/{sid}/copy/", {"name": "新套件", "expected_version": 2}, format="json"
        ).status_code
        == 201
    )
    assert (
        session_client.post(base + f"suites/{sid}/publish/", {"expected_version": 2}, format="json").status_code == 200
    )
    resource = session_client.post(base + "test-resources/", {"name": "测试环境", "kind": "environment"}, format="json")
    assert resource.status_code == 201, resource.data
    rid = resource.data["id"]
    assert (
        session_client.patch(
            base + f"test-resources/{rid}/", {"expected_version": 1, "description": "测试员维护环境"}, format="json"
        ).status_code
        == 200
    )
    plan = session_client.post(
        base + "plans/",
        {"name": "测试员计划", "build": "v1", "environment": "local", "suite_id": sid, "managed": True},
        format="json",
    )
    assert plan.status_code == 201, plan.data
    pid = plan.data["id"]
    item = plan.data["items"][0]["id"]
    assert (
        session_client.patch(
            base + f"plans/{pid}/", {"expected_version": 1, "name": "维护计划"}, format="json"
        ).status_code
        == 200
    )
    assert (
        session_client.post(
            base + f"plans/{pid}/copy/", {"name": "复制计划", "expected_version": 2}, format="json"
        ).status_code
        == 201
    )
    resources = session_client.post(
        base + f"plans/{pid}/resources/", {"expected_version": 2, "resource_ids": [rid]}, format="json"
    )
    assert resources.status_code == 200, resources.data
    workflow = base + f"plans/{pid}/workflow/"

    def step(action, version, **extra):
        response = session_client.post(
            workflow, {"action": action, "expected_version": version, **extra}, format="json"
        )
        assert response.status_code == 200, (action, response.data)
        return response.data

    step("assign", 3, assignee_id=str(tester.id))
    step("claim", 4)
    step("pause", 5)
    step("resume", 6)
    execution = session_client.post(
        base + f"items/{item}/executions/", {"request_id": str(uuid4()), "result": "passed"}, format="json"
    )
    assert execution.status_code == 201, execution.data
    assert TestExecution.objects.get(pk=execution.data["id"]).created_by_id == tester.id
    step("submit", 7)
    report = session_client.post(
        base + "reports/", {"name": "测试员报告", "request_id": str(uuid4()), "plan_ids": [pid]}, format="json"
    )
    assert report.status_code == 201, report.data
    report_id = report.data["id"]
    assert (
        session_client.patch(
            base + f"reports/{report_id}/", {"name": "测试员重命名", "expected_version": 1}, format="json"
        ).status_code
        == 200
    )
    assert (
        session_client.post(
            base + f"reports/{report_id}/conclusion/",
            {"expected_version": 2, "result": "passed", "summary": "测试员不能经理签署"},
            format="json",
        ).status_code
        == 403
    )
    assert session_client.post(workflow, {"action": "approve", "expected_version": 8}, format="json").status_code == 403
    assert (
        session_client.post(
            workflow, {"action": "return", "expected_version": 8, "comment": "不能自己经理验收"}, format="json"
        ).status_code
        == 403
    )
    session_client.force_authenticate(manager)
    step("approve", 8)
    assert PlanEvent.objects.filter(plan_id=pid, action="approve", created_by=manager).exists()


def test_tester_asset_lifecycle_does_not_grant_release_account_or_global_settings(session_client, tester_scope):
    project, tester, manager, base = tester_scope
    case = session_client.post(
        base + "cases/", {"title": "生命周期用例", "steps": [{"action": "运行", "expected": "通过"}]}, format="json"
    )
    assert case.status_code == 201, case.data
    cid = case.data["id"]
    for action, version in [("trash", 1), ("untrash", 2), ("archive", 3), ("restore", 4)]:
        response = session_client.post(
            base + "bulk-actions/",
            {
                "resource": "cases",
                "action": action,
                "items": [{"id": cid, "version": version}],
                "reason": "测试员整理用例",
            },
            format="json",
        )
        assert response.status_code == 200, (action, response.data)
    assert QualityLifecycleEvent.objects.filter(object_id=cid, created_by=tester).count() == 4
    for endpoint, data in [
        ("releases/", {}),
        ("versions/", {}),
        ("roles/", {"user_id": str(tester.id), "role": "PLATFORM_ADMIN"}),
        ("integrations/connections/", {"kind": "data_platform"}),
    ]:
        assert session_client.post(base + endpoint, data, format="json").status_code == 403, endpoint
    assert (
        session_client.patch(
            base.replace("/quality/", "/knowledge/") + "configuration/", {"model": "not-allowed"}, format="json"
        ).status_code
        == 403
    )
    assert (
        session_client.patch(
            "/api/quality-auth/accounts/", {"user_id": str(tester.id), "administrator": True}, format="json"
        ).status_code
        == 403
    )


def test_retired_data_regression_is_unavailable_to_tester_and_reporter(session_client, tester_scope):
    from plane.quality.models import Defect, TestPlan

    project, tester, manager, base = tester_scope
    defect = Defect.objects.create(project=project, title="独立平台缺陷", assignee=manager)
    endpoint = base + f"defects/{defect.id}/data-regressions/"
    count = TestPlan.objects.filter(project=project).count()
    assert session_client.post(endpoint, {"environment": "回归测试"}, format="json").status_code == 404
    reporter = User.objects.create(email="no-regression@tester.invalid", username="no-regression")
    WorkspaceMember.objects.create(workspace=project.workspace, member=reporter, role=15)
    ProjectMember.objects.create(project=project, member=reporter, role=15)
    BusinessRole.objects.create(project=project, user=reporter, role="REPORTER")
    session_client.force_authenticate(reporter)
    assert session_client.post(endpoint, {"environment": "不能绕过"}, format="json").status_code == 404
    assert TestPlan.objects.filter(project=project).count() == count
