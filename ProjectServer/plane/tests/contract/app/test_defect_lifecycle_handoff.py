"""A reported defect keeps one actionable owner through review and verification."""

from uuid import uuid4

import pytest
from django.utils import timezone

from plane.db.models import Notification, Project, ProjectMember, User, WorkspaceMember
from plane.quality.models import (
    BusinessRole, CaseRevision, Defect, DefectVerification, DefectVerificationEvent,
    DefectVerificationResult, ModuleCatalog, ModuleOwner, PlanItem, ProjectRolePolicy,
    Solution, SolutionRevision, TestCase, TestExecution, TestPlan,
)
from plane.quality.solutions import FIELDS

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def lifecycle(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="交接回归", identifier="HANDOFF")
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    manager = create_user
    ProjectMember.objects.create(project=project, member=manager, role=20)
    BusinessRole.objects.create(project=project, user=manager, role="PROJECT_MANAGER")
    users = []
    for name, role in [("repairer", "TECHNICIAN"), ("verifier", "REGRESSION_TESTER")]:
        user = User.objects.create(username=f"handoff-{name}", email=f"handoff-{name}@test.invalid")
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(project=project, member=user, role=15)
        BusinessRole.objects.create(project=project, user=user, role=role)
        users.append(user)
    module = ModuleCatalog.objects.create(key="handoff-module", name="交接模块")
    ModuleOwner.objects.create(workspace=workspace, module=module, user=users[0])
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    todos = "/api/quality-auth/my-todos/"
    return project, manager, users[0], users[1], base, todos


def rows(client, url, workspace, kind):
    response = client.get(url, {"workspace": workspace.slug, "kind": kind})
    assert response.status_code == 200, response.content
    return response.data["results"]


def approved_solution(project, defect, technician, manager):
    solution = Solution.objects.create(
        project=project, created_by=technician, defect=defect, title="修复方案",
        root_cause="定位原因", steps="修复边界", verification="执行回归",
        status="approved", submitted_version=1,
    )
    revision = SolutionRevision.objects.create(
        project=project, created_by=technician, solution=solution, version=1,
        snapshot={key: getattr(solution, key) for key in FIELDS},
        reviewer_ids=[str(manager.id)], required_count=1,
    )
    return solution, revision


def test_report_entries_assign_valid_owner_and_keep_explicit_choice(session_client, lifecycle):
    project, manager, technician, tester, base, todos = lifecycle
    session_client.force_authenticate(tester)
    unknown = session_client.post(base + "defects/", {"title": "未知故障"}, format="json")
    assert unknown.status_code == 201, unknown.content
    defect = Defect.objects.get(pk=unknown.data["id"])
    assert defect.assignee_id == manager.id and defect.assignment_origin == "triage"
    assert Notification.objects.filter(receiver=manager, entity_identifier=defect.id).exists()
    session_client.force_authenticate(manager)
    assert any(row["id"] == str(defect.id) for row in rows(session_client, todos, project.workspace, "defect"))

    session_client.force_authenticate(tester)
    reported = session_client.post(base + "defects/", {
        "title": "模块故障", "description": "受影响模块：交接模块",
    }, format="json")
    assert reported.status_code == 201, reported.content
    routed = Defect.objects.get(pk=reported.data["id"])
    assert routed.assignee_id == technician.id and routed.assignment_origin == "initial"
    assert Notification.objects.filter(receiver=manager, entity_identifier=routed.id).exists()
    session_client.force_authenticate(technician)
    assert any(row["id"] == str(routed.id) for row in rows(session_client, todos, project.workspace, "defect"))

    session_client.force_authenticate(manager)
    chosen = session_client.post(base + "defects/", {
        "title": "指定负责人", "assignee_id": str(technician.id),
    }, format="json")
    assert chosen.status_code == 201, chosen.content
    direct = Defect.objects.get(pk=chosen.data["id"])
    assert direct.assignee_id == technician.id and direct.assignment_origin != "triage"

    session_client.force_authenticate(tester)
    source = session_client.post(base + "source-defects/", {
        "source_system": "test", "source_instance": "local", "record_type": "failure",
        "record_id": uuid4().hex, "title": "来源故障", "description": "未标识模块",
    }, format="json")
    assert source.status_code == 201, source.content
    source_defect = Defect.objects.get(pk=source.data["defect"]["id"])
    assert source_defect.assignee_id == manager.id and source_defect.assignment_origin == "triage"
    assert Notification.objects.filter(receiver=manager, entity_identifier=source_defect.id).exists() or source_defect.created_by_id == manager.id

    case = TestCase.objects.create(project=project, created_by=manager, title="失败用例", steps=[])
    revision = CaseRevision.objects.create(project=project, created_by=manager, case=case, version=1, title=case.title, snapshot={"steps": []})
    plan = TestPlan.objects.create(project=project, created_by=manager, name="失败计划", build="v1", environment="local", assignee=tester)
    item = PlanItem.objects.create(project=project, created_by=manager, plan=plan, case=case, revision=revision)
    execution = TestExecution.objects.create(project=project, created_by=tester, item=item, request_id=uuid4(), result="failed", actual_result="复现")
    session_client.force_authenticate(tester)
    from_execution = session_client.post(base + f"executions/{execution.id}/defect/", {}, format="json")
    assert from_execution.status_code == 201, from_execution.content
    execution_defect = Defect.objects.get(pk=from_execution.data["id"])
    assert execution_defect.assignee_id == manager.id and execution_defect.assignment_origin == "triage"


def test_handoff_todos_follow_approved_revision_and_manager_review(session_client, lifecycle):
    project, manager, technician, tester, base, todos = lifecycle
    defect = Defect.objects.create(project=project, created_by=tester, assignee=technician, title="待修复")
    solution, revision = approved_solution(project, defect, technician, manager)
    defect.status, defect.fixed_build, defect.resolved_at = "resolved", "v2", timezone.now()
    defect.save(update_fields=["status", "fixed_build", "resolved_at"])
    plan = TestPlan.objects.create(project=project, created_by=technician, name="回归", build="v2", environment="local", assignee=tester, round_no=1)
    round_ = DefectVerification.objects.create(
        project=project, created_by=technician, defect=defect, plan=plan, round_no=1,
        mode="manual", status="testing", fixed_build="v2", environment="local",
        resolved_at=defect.resolved_at, request_id=uuid4(), request_hash="handoff",
        steps=[{"action": "复测", "expected": "正常"}],
    )
    DefectVerificationEvent.objects.create(
        project=project, created_by=technician, verification=round_, request_id=uuid4(),
        request_hash="bound", action="solution_bound", snapshot={"solution_revision_id": str(revision.id)},
    )
    session_client.force_authenticate(technician)
    assert not any(row["id"] == str(defect.id) and row["next_action"] == "安排回归" for row in rows(session_client, todos, project.workspace, "defect"))
    session_client.force_authenticate(tester)
    assert any(row["id"] == str(plan.id) and row["next_action"] == "执行验证" for row in rows(session_client, todos, project.workspace, "plan"))
    round_.status = "review"
    round_.save(update_fields=["status"])
    session_client.force_authenticate(manager)
    assert any(row["id"] == str(plan.id) and row["next_action"] == "验收结果" for row in rows(session_client, todos, project.workspace, "plan"))
    round_.status = "testing"
    round_.save(update_fields=["status"])
    session_client.force_authenticate(tester)

    solution.steps = "新的修复步骤"
    solution.save(update_fields=["steps"])
    assert not any(row["id"] == str(plan.id) and row["next_action"] == "执行验证" for row in rows(session_client, todos, project.workspace, "plan"))
    solution.status, solution.submitted_version = "approved", 2
    solution.save(update_fields=["status", "submitted_version"])
    SolutionRevision.objects.create(
        project=project, created_by=technician, solution=solution, version=2,
        snapshot={key: getattr(solution, key) for key in FIELDS},
        reviewer_ids=[str(manager.id)], required_count=1,
    )
    assert not any(row["id"] == str(plan.id) and row["next_action"] == "执行验证" for row in rows(session_client, todos, project.workspace, "plan"))
    round_.status = "review"
    round_.save(update_fields=["status"])
    session_client.force_authenticate(manager)
    assert not any(row["id"] == str(plan.id) and row["next_action"] == "验收结果" for row in rows(session_client, todos, project.workspace, "plan"))


def test_new_solution_revision_removes_old_pass_from_current_statistics(session_client, lifecycle):
    project, manager, technician, tester, base, _ = lifecycle
    defect = Defect.objects.create(
        project=project, created_by=technician, assignee=technician, title="旧实测",
        status="resolved", fixed_build="v2", resolved_at=timezone.now(),
    )
    solution, revision = approved_solution(project, defect, technician, manager)
    plan = TestPlan.objects.create(project=project, created_by=technician, name="人工验证", build="v2", environment="local", assignee=tester, round_no=1)
    round_ = DefectVerification.objects.create(
        project=project, created_by=technician, defect=defect, plan=plan, round_no=1,
        mode="manual", status="testing", fixed_build="v2", environment="local",
        resolved_at=defect.resolved_at, request_id=uuid4(), request_hash="round", steps=[{"action": "检查", "expected": "通过"}],
    )
    DefectVerificationEvent.objects.create(
        project=project, created_by=technician, verification=round_, request_id=uuid4(), request_hash="binding",
        action="solution_bound", snapshot={"solution_revision_id": str(revision.id)},
    )
    DefectVerificationResult.objects.create(
        project=project, created_by=tester, verification=round_, request_id=uuid4(), request_hash="passed",
        result="passed", actual_result="旧方案实测通过", evidence="", step_results=[{"result": "passed", "actual": "通过"}],
    )
    assert session_client.get(base + "report/").data["manual_verification"]["passed"] == 1
    assert session_client.get(base + "verification-results/", {"current_only": "true"}).data["count"] == 1
    solution.steps = "新修复步骤"
    solution.save(update_fields=["steps"])
    solution.submitted_version = 2
    solution.save(update_fields=["submitted_version"])
    SolutionRevision.objects.create(
        project=project, created_by=technician, solution=solution, version=2,
        snapshot={key: getattr(solution, key) for key in FIELDS}, reviewer_ids=[str(manager.id)], required_count=1,
    )
    assert session_client.get(base + "report/").data["manual_verification"]["passed"] == 0
    assert session_client.get(base + "verification-results/", {"current_only": "true"}).data["count"] == 0
    assert session_client.get(base + "verification-results/").data["count"] == 1
    owners = session_client.get(base + "owner-statistics/", {"source": "quality", "metric": "manual_total"})
    assert owners.status_code == 200 and owners.data["total"] == 0, owners.content
