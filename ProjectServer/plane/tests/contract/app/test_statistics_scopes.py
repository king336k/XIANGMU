"""Current validation, historical activity and reusable case counts have separate units."""

from uuid import uuid4
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember
from plane.quality.models import (
    TestCase,
    CaseRevision,
    TestPlan,
    PlanItem,
    TestExecution,
    Defect,
    DefectVerification,
    DefectVerificationResult,
    SavedReport,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def scope(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="统计口径", identifier="STAT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    return project, base, create_user


def case_plan(project, actor, name="计划", **kw):
    case = TestCase.objects.create(project=project, created_by=actor, title=name, steps=[])
    revision = CaseRevision.objects.create(
        project=project, created_by=actor, case=case, title=name, version=1, snapshot={"steps": []}
    )
    plan = TestPlan.objects.create(project=project, created_by=actor, name=name, build="v2", environment="测试", **kw)
    item = PlanItem.objects.create(project=project, created_by=actor, case=case, revision=revision, plan=plan)
    return case, plan, item


def execute(project, actor, item, result="passed", round_no=1):
    return TestExecution.objects.create(
        project=project, created_by=actor, item=item, request_id=uuid4(), result=result, round_no=round_no
    )


def verification(project, actor, defect, number, mode="manual", plan=None, status="accepted"):
    return DefectVerification.objects.create(
        project=project,
        created_by=actor,
        defect=defect,
        round_no=number,
        mode=mode,
        status=status,
        fixed_build="v2",
        environment="测试",
        resolved_at=defect.resolved_at,
        request_id=uuid4(),
        request_hash="x",
        plan=plan,
    )


def test_overview_separates_manual_current_round_from_history_and_active_library(session_client, scope):
    project, base, actor = scope
    defect = Defect.objects.create(
        project=project,
        created_by=actor,
        title="人工验收",
        status="closed",
        fixed_build="v2",
        resolved_at=timezone.now(),
    )
    old = verification(project, actor, defect, 1, status="returned_test")
    current = verification(project, actor, defect, 2)
    for row, result in [(old, "passed"), (current, "failed"), (current, "passed")]:
        DefectVerificationResult.objects.create(
            project=project,
            created_by=actor,
            verification=row,
            request_id=uuid4(),
            request_hash="x",
            result=result,
            actual_result="实测",
            evidence="截图",
        )
    case, plan, item = case_plan(project, actor)
    execute(project, actor, item)
    hidden_case, hidden_plan, hidden_item = case_plan(project, actor, "归档", archived_at=timezone.now())
    hidden_case.archived_at = timezone.now()
    hidden_case.save()
    execute(project, actor, hidden_item, "failed")
    Defect.objects.create(project=project, title="归档未关", archived_at=timezone.now())
    data = session_client.get(base + "report/").data
    assert data["summary"]["total"] == 1 and data["summary"]["passed"] == 1
    assert data["manual_verification"]["total"] == 1 and data["manual_verification"]["passed"] == 1
    assert data["manual_execution_count"] == 3 and data["execution_count"] == 2
    assert data["plan_count"] == 1 and data["historical_plan_count"] == 2
    assert data["case_count"] == 1 and data["open_defects"] == 0
    assert data["closed_defects"] == 1
    for result in ["passed", "failed", "blocked", "inconclusive", "skipped", "pending"]:
        filtered = session_client.get(base + f"verification-results/?current_only=true&mode=manual&result={result}")
        assert filtered.status_code == 200
        assert filtered.data["count"] == data["manual_verification"][result]
    manual = session_client.get(base + "verification-results/?current_only=true&mode=manual")
    assert manual.status_code == 200 and manual.data["count"] == data["manual_verification"]["total"] == 1
    assert manual.data["results"][0]["current"]["id"] == str(current.id)
    assert manual.data["results"][0]["current"]["summary"]["passed"] == data["manual_verification"]["passed"]
    defect.fixed_build = "v3"
    defect.save()
    assert session_client.get(base + "verification-results/?current_only=true&mode=manual").data["count"] == 0
    assert session_client.get(base + "verification-results/").data["count"] == 1


def test_old_verification_plan_and_changed_build_do_not_inflate_current_pass(session_client, scope):
    project, base, actor = scope
    case, old_plan, old_item = case_plan(project, actor, "旧轮", status="cancelled")
    defect = Defect.objects.create(
        project=project, title="验证", fixed_build="v2", status="resolved", resolved_at=timezone.now()
    )
    verification(project, actor, defect, 1, mode="cases", plan=old_plan, status="returned_test")
    execute(project, actor, old_item)
    plan = TestPlan.objects.create(
        project=project, name="本轮", build="v2", environment="测试", round_no=2, status="running"
    )
    item = PlanItem.objects.create(project=project, plan=plan, case=case, revision=old_item.revision)
    verification(project, actor, defect, 2, mode="cases", plan=plan, status="testing")
    execute(project, actor, item, round_no=1)  # another round cannot count even for an unmanaged plan
    data = session_client.get(base + "report/").data
    assert data["summary"]["total"] == 1 and data["summary"]["pending"] == 1
    execute(project, actor, item, round_no=2)
    assert session_client.get(base + "report/").data["summary"]["passed"] == 1
    defect.fixed_build = "v3"
    defect.save()
    data = session_client.get(base + "report/").data
    assert data["summary"]["total"] == 0 and data["execution_count"] == 3
    assert data["historical_plan_count"] == 2


def test_plan_snapshot_links_its_verification_defect_and_archived_history_stays_readable(session_client, scope):
    project, base, actor = scope
    case, plan, item = case_plan(project, actor, status="completed", archived_at=timezone.now())
    execute(project, actor, item)
    defect = Defect.objects.create(
        project=project, title="关联验收缺陷", status="closed", fixed_build="v2", resolved_at=timezone.now()
    )
    verification(project, actor, defect, 1, mode="cases", plan=plan)
    saved = session_client.post(
        base + "reports/",
        {"name": "历史计划", "plan_id": str(plan.id), "request_id": str(uuid4())},
        format="json",
    )
    assert saved.status_code == 201, saved.content
    snapshot = saved.data["snapshot"]
    assert snapshot["summary"]["passed"] == 1
    assert [row["id"] for row in snapshot["defects"]] == [str(defect.id)]
    assert snapshot["scope"] == "historical_plan"
    original = SavedReport.objects.get(pk=saved.data["id"]).snapshot
    defect.status = "open"
    defect.save()
    assert session_client.get(base + f"reports/{saved.data['id']}/").data["snapshot"] == original


def test_period_history_survives_archive_manual_activity_and_current_drilldown_agree(session_client, scope):
    project, base, actor = scope
    case, archived, item = case_plan(project, actor, archived_at=timezone.now())
    execute(project, actor, item)
    empty_case, cancelled, empty_item = case_plan(project, actor, "旧取消", status="cancelled")
    defect = Defect.objects.create(
        project=project, title="人工", status="closed", fixed_build="v2", resolved_at=timezone.now()
    )
    row = verification(project, actor, defect, 1)
    DefectVerificationResult.objects.create(
        project=project,
        created_by=actor,
        verification=row,
        request_id=uuid4(),
        request_hash="x",
        result="passed",
        actual_result="成功",
        evidence="截图",
    )
    day = timezone.localtime().date().isoformat()
    url = base + f"project-report/?start={day}&end={day}"
    data = session_client.get(url).data
    assert data["activity"]["test_executions"] == 1
    assert data["activity"]["manual_executions"] == 1
    assert data["manual_results"]["passed"] == 1
    assert data["current"]["plans_unfinished"] == 0
    assert session_client.get(url + "&detail=test_executions").data["count"] == 1
    manual = session_client.get(url + "&detail=manual_executions")
    assert manual.status_code == 200 and manual.data["count"] == 1
    assert session_client.get(url + "&detail=current_plans").data["count"] == 0


def test_current_verification_requires_case_revision_and_repair_timestamp_and_review_is_workload(session_client, scope):
    project, base, actor = scope
    case, plan, item = case_plan(project, actor, status="review")
    execute(project, actor, item)
    defect = Defect.objects.create(
        project=project, title="待验收", fixed_build="v2", status="resolved", resolved_at=timezone.now()
    )
    verification(project, actor, defect, 1, mode="cases", plan=plan, status="review")
    day = timezone.localtime().date().isoformat()
    url = base + f"project-report/?start={day}&end={day}"
    data = session_client.get(url).data
    assert data["current"]["plans_unfinished"] == 1
    assert data["unassigned"]["plans"]["review"] == 1
    drill = session_client.get(url + "&detail=workload&resource=plans&status=review&assignee_id=unassigned")
    assert drill.status_code == 200 and drill.data["count"] == 1
    case.version = 2
    case.save()
    assert session_client.get(base + "report/").data["summary"]["total"] == 0
    assert session_client.get(url).data["current"]["plans_unfinished"] == 0
    case.version = 1
    case.save()
    defect.resolved_at = timezone.now()
    defect.save()
    assert session_client.get(base + "report/").data["summary"]["total"] == 0


def test_manual_only_saved_report_keeps_actual_evidence_and_can_sign_accepted_round(session_client, scope):
    project, base, actor = scope
    defect = Defect.objects.create(
        project=project, title="人工", status="closed", fixed_build="v2", resolved_at=timezone.now()
    )
    row = verification(project, actor, defect, 1)
    actual = DefectVerificationResult.objects.create(
        project=project,
        created_by=actor,
        verification=row,
        request_id=uuid4(),
        request_hash="x",
        result="passed",
        actual_result="现场成功",
        evidence="证据地址",
    )
    saved = session_client.post(base + "reports/", {"name": "人工验证报告", "request_id": str(uuid4())}, format="json")
    assert saved.status_code == 201, saved.content
    snapshot = saved.data["snapshot"]
    assert snapshot["summary"]["total"] == 0
    assert snapshot["manual_verification"]["passed"] == 1 and snapshot["manual_verification"]["accepted"] == 1
    assert snapshot["manual_validations"][0]["latest_result"]["id"] == str(actual.id)
    assert snapshot["manual_validations"][0]["latest_result"]["evidence"] == "证据地址"
    assert snapshot["manual_execution_count"] == 1
    conclusion = session_client.post(
        base + f"reports/{saved.data['id']}/conclusion/",
        {"expected_version": 1, "result": "passed", "summary": "人工经理验收完成"},
        format="json",
    )
    assert conclusion.status_code == 201, conclusion.content
    download = session_client.get(base + f"reports/{saved.data['id']}/download/")
    assert "人工验证（独立验证轮次）" in download.content.decode()
    DefectVerificationResult.objects.create(
        project=project,
        created_by=actor,
        verification=row,
        request_id=uuid4(),
        request_hash="y",
        result="failed",
        actual_result="后续失败",
        evidence="证据",
    )
    assert session_client.get(base + f"reports/{saved.data['id']}/").data["snapshot"] == snapshot


def test_period_completed_verification_and_archived_defect_history_remain_countable(session_client, scope):
    from plane.quality.models import DefectVerificationEvent, DefectEvent

    project, base, actor = scope
    case, plan, item = case_plan(project, actor, status="completed", archived_at=timezone.now())
    defect = Defect.objects.create(
        project=project,
        title="已归档缺陷",
        status="closed",
        fixed_build="v2",
        resolved_at=timezone.now(),
        archived_at=timezone.now(),
    )
    row = verification(project, actor, defect, 1, mode="cases", plan=plan)
    DefectVerificationEvent.objects.create(
        project=project, created_by=actor, verification=row, request_id=uuid4(), request_hash="x", action="accept"
    )
    DefectEvent.objects.create(
        project=project, created_by=actor, defect=defect, previous_status="resolved", status="closed"
    )
    day = timezone.localtime().date().isoformat()
    url = base + f"project-report/?start={day}&end={day}"
    data = session_client.get(url).data
    assert data["activity"]["plans_confirmed"] == 1
    assert data["activity"]["defects_created"] == 1 and data["activity"]["defects_closed"] == 1
    assert data["current"]["defects_unclosed"] == 0
    assert session_client.get(url + "&detail=plans_confirmed").data["count"] == 1
    assert session_client.get(url + "&detail=defects_closed").data["count"] == 1


@pytest.mark.parametrize("blocker", ["pending_manual", "unclosed_defect"])
def test_manual_report_cannot_sign_passed_when_any_scope_is_incomplete(session_client, scope, blocker):
    project, base, actor = scope
    defect = Defect.objects.create(
        project=project, title="人工", status="closed", fixed_build="v2", resolved_at=timezone.now()
    )
    row = verification(project, actor, defect, 1)
    DefectVerificationResult.objects.create(
        project=project,
        created_by=actor,
        verification=row,
        request_id=uuid4(),
        request_hash="x",
        result="passed",
        actual_result="成功",
        evidence="截图",
    )
    pending = Defect.objects.create(
        project=project,
        title="阻止通过",
        status="open" if blocker == "unclosed_defect" else "resolved",
        fixed_build="v2",
        resolved_at=timezone.now(),
    )
    if blocker == "pending_manual":
        verification(project, actor, pending, 1, status="testing")
    saved = session_client.post(base + "reports/", {"name": "不能签通过", "request_id": str(uuid4())}, format="json")
    assert saved.status_code == 201, saved.content
    signed = session_client.post(
        base + f"reports/{saved.data['id']}/conclusion/",
        {"expected_version": 1, "result": "passed", "summary": "不得忽略未完成"},
        format="json",
    )
    assert signed.status_code == 400, signed.content


def test_current_drilldowns_match_summary_and_default_execution_history_stays_complete(session_client, scope):
    project, base, actor = scope
    case, active, item = case_plan(project, actor)
    execute(project, actor, item, "failed")
    latest = execute(project, actor, item, "passed", round_no=2)  # unmanaged legacy remains latest-any-round
    _, cancelled, cancelled_item = case_plan(project, actor, "已取消", status="cancelled")
    execute(project, actor, cancelled_item, "failed")
    _, managed, managed_item = case_plan(project, actor, "受管", managed=True, round_no=2, status="running")
    execute(project, actor, managed_item, "passed", round_no=1)
    current_failure = execute(project, actor, managed_item, "failed", round_no=2)
    summary = session_client.get(base + "report/").data["summary"]
    plans = session_client.get(base + "plans/?current_only=true")
    assert plans.status_code == 200 and plans.data["count"] == 2
    assert {row["id"] for row in plans.data["results"]} == {str(active.id), str(managed.id)}
    assert summary["passed"] == 1 and summary["failed"] == 1
    executions = session_client.get(base + "executions/?current_only=true")
    assert executions.status_code == 200 and executions.data["count"] == summary["executed"] == 2
    assert {row["id"] for row in executions.data["results"]} == {str(latest.id), str(current_failure.id)}
    for result in ["passed", "failed", "blocked", "inconclusive", "skipped"]:
        response = session_client.get(base + f"executions/?current_only=true&result={result}")
        assert response.status_code == 200 and response.data["count"] == summary[result]
    assert session_client.get(base + "executions/").data["count"] == 5
    assert session_client.get(base + "plans/").data["count"] == 3


def test_manual_result_drilldowns_use_latest_result_and_include_accepted_closed(session_client, scope):
    project, base, actor = scope
    for index, result in enumerate(["passed", "failed", "blocked", "inconclusive", "skipped", "pending"]):
        defect = Defect.objects.create(
            project=project,
            title=result,
            status="closed" if result == "passed" else "resolved",
            fixed_build="v2",
            resolved_at=timezone.now(),
        )
        row = verification(project, actor, defect, 1, status="accepted" if result == "passed" else "testing")
        if result != "pending":
            for outcome in ["failed", result]:
                DefectVerificationResult.objects.create(
                    project=project,
                    verification=row,
                    created_by=actor,
                    request_id=uuid4(),
                    request_hash="x",
                    result=outcome,
                    actual_result="实测",
                )
    report = session_client.get(base + "report/").data
    assert report["closed_defects"] == 1
    assert report["manual_verification"]["total"] == 6
    for result in ["passed", "failed", "blocked", "inconclusive", "skipped", "pending"]:
        response = session_client.get(base + f"verification-results/?current_only=true&mode=manual&result={result}")
        assert response.status_code == 200
        assert response.data["count"] == report["manual_verification"][result] == 1
        assert response.data["results"][0]["title"] == result
    closed = session_client.get(base + "defects/?status=closed")
    assert closed.status_code == 200 and closed.data["count"] == report["closed_defects"]
    assert (
        session_client.get(base + "verification-results/?current_only=true&mode=manual&result=invalid").status_code
        == 400
    )
