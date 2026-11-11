"""45100 fresh-data regression uses native plans and server-verified source evidence."""

from uuid import uuid4
from datetime import timedelta
import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember, WorkspaceMember, Issue, User
from plane.quality.models import Defect, DaqBinding, DaqReport, PlatformProject, Solution, SolutionRevision

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def data_flow(session_client, workspace, create_user, settings):
    project = Project.objects.create(workspace=workspace, name="重新采集回归", identifier="FRESH")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    tester = User.objects.create(email="fresh-tester@local.test", username="fresh-tester")
    WorkspaceMember.objects.create(workspace=workspace, member=tester, role=15)
    ProjectMember.objects.create(project=project, member=tester, role=15)
    issue = Issue.objects.create(project=project, workspace=workspace, name="采集任务")
    binding = DaqBinding.objects.create(
        project=project,
        created_by=create_user,
        source_instance="platform-test",
        platform_task_id=24,
        source_record_id="old-session",
        package_id="old-package",
        issue=issue,
    )
    PlatformProject.objects.create(project=project, source_instance="platform-test", external_project_id=3)
    defect = Defect.objects.create(
        project=project,
        created_by=create_user,
        title="采集异常",
        fixed_build="v2",
        status="resolved",
        resolved_at=timezone.now(),
    )
    DaqReport.objects.create(
        project=project, binding=binding, defect=defect, request_id=uuid4(), request_hash="hash", category="Other"
    )
    solution = Solution.objects.create(
        project=project,
        created_by=create_user,
        defect=defect,
        title="修复方案",
        root_cause="连接恢复问题",
        steps="修复连接",
        verification="重新采集后检查日志和数据包",
        status="approved",
        submitted_version=1,
    )
    SolutionRevision.objects.create(
        project=project,
        created_by=create_user,
        solution=solution,
        version=1,
        snapshot={"title": "修复方案", "verification": solution.verification},
        reviewer_ids=[str(create_user.id)],
        required_count=1,
    )
    settings.QUALITY_PLATFORM_SOURCES = {"platform-test": {"timezone": "Asia/Shanghai"}}
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    return base, project, defect, solution, tester, create_user


def start(client, flow, **parameters):
    base, project, defect, solution, tester, manager = flow
    created = client.post(
        base + f"defects/{defect.id}/data-regressions/",
        {"solution_id": str(solution.id), "environment": "本地验证", **parameters},
        format="json",
    )
    assert created.status_code == 201, created.content
    plan = created.data["plan"]

    def action(verb, **extra):
        return client.post(
            base + f"plans/{plan['id']}/workflow/",
            {"action": verb, "expected_version": plan["workflow_version"], **extra},
            format="json",
        )

    plan = action("assign", assignee_id=str(tester.id)).data
    client.force_authenticate(user=tester)
    plan = action("claim").data
    return created.data, plan


def authoritative_context(**overrides):
    return {
        "projectId": 3,
        "taskId": 24,
        "sourceSessionId": "new-session",
        "dataPackageId": "new-package",
        "collectedAt": timezone.now().isoformat(),
        "deviceName": "robot-test",
        **overrides,
    }


def test_new_data_plan_requires_authoritative_fresh_data_before_pass(session_client, data_flow, mocker):
    base, *_ = data_flow
    regression, plan = start(session_client, data_flow)
    execute = base + f"items/{plan['items'][0]['id']}/executions/"
    result = session_client.post(
        execute, {"request_id": str(uuid4()), "result": "passed", "actual_result": "通过"}, format="json"
    )
    assert result.status_code == 400
    mocker.patch("plane.quality.platform.fetch", return_value=authoritative_context())
    evidence = session_client.post(
        base + f"plans/{plan['id']}/data-evidence/", {"source_session_id": "new-session"}, format="json"
    )
    assert evidence.status_code == 201, evidence.content
    assert evidence.data["package_id"] == "new-package" and evidence.data["round_no"] == 1
    result = session_client.post(
        execute,
        {
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": "修复版本采集正常",
            "evidence": "日志检查无异常",
        },
        format="json",
    )
    assert result.status_code == 201, result.content


@pytest.mark.parametrize(
    "context",
    [
        {"projectId": 999},
        {"taskId": 999},
        {"sourceSessionId": "wrong"},
        {"dataPackageId": "old-package"},
        {"collectedAt": "invalid"},
        {"collectedAt": "2026-99-99T00:00:00"},
        {"dataPackageId": "x" * 256},
        {"dataReady": False, "dataPackageStatus": "Transferring"},
        {"dataReady": "true", "dataPackageStatus": "PendingAnnotation"},
        {"dataReady": True, "dataPackageStatus": "ConvertFailed"},
        {"collectedAt": (timezone.now() - timedelta(days=1)).isoformat()},
    ],
)
def test_old_or_foreign_data_rejected(session_client, data_flow, mocker, context):
    base, *_ = data_flow
    regression, plan = start(session_client, data_flow)
    mocker.patch("plane.quality.platform.fetch", return_value=authoritative_context(**context))
    response = session_client.post(
        base + f"plans/{plan['id']}/data-evidence/", {"source_session_id": "new-session"}, format="json"
    )
    assert response.status_code == 400, response.content


def test_data_regression_approval_closes_only_after_manager_and_generates_draft(session_client, data_flow, mocker):
    base, project, defect, solution, tester, manager = data_flow
    regression, plan = start(session_client, data_flow)
    mocker.patch("plane.quality.platform.fetch", return_value=authoritative_context())
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/data-evidence/", {"source_session_id": "new-session"}, format="json"
        ).status_code
        == 201
    )
    assert (
        session_client.post(
            base + f"items/{plan['items'][0]['id']}/executions/",
            {
                "request_id": str(uuid4()),
                "result": "passed",
                "actual_result": "新数据验证正常",
                "evidence": "检查了上传后的新数据和日志",
            },
            format="json",
        ).status_code
        == 201
    )
    submitted = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "submit", "expected_version": plan["workflow_version"]},
        format="json",
    )
    assert submitted.status_code == 200, submitted.content
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/workflow/",
            {"action": "approve", "expected_version": submitted.data["workflow_version"]},
            format="json",
        ).status_code
        == 403
    )
    session_client.force_authenticate(user=manager)
    approved = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "approve", "expected_version": submitted.data["workflow_version"]},
        format="json",
    )
    assert approved.status_code == 200, approved.content
    defect.refresh_from_db()
    assert defect.status == "closed"
    from plane.knowledge.models import Article

    article = Article.objects.get(project=project, status="draft", source_issue=defect.repair_issue)
    assert article.source_defect_id == defect.id
    assert article.source_regression_id is not None
    assert "根因" in article.content and "修复步骤" in article.content
    article.status, article.publication_active = "published", True
    article.save()
    reopened = session_client.patch(base + f"defects/{defect.id}/", {
        "status": "open", "expected_version": defect.edit_version, "resolution": "现场同类问题复现",
    }, format="json")
    assert reopened.status_code == 200, reopened.content
    article.refresh_from_db()
    assert article.status == "offline" and article.publication_active is False
    assert article.events.filter(action="source_reopened").exists()


def test_return_starts_new_collection_boundary_and_old_round_is_not_reused(session_client, data_flow, mocker):
    base, project, defect, solution, tester, manager = data_flow
    regression, plan = start(session_client, data_flow)
    mocker.patch("plane.quality.platform.fetch", return_value=authoritative_context())
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/data-evidence/", {"source_session_id": "new-session"}, format="json"
        ).status_code
        == 201
    )
    assert (
        session_client.post(
            base + f"items/{plan['items'][0]['id']}/executions/",
            {"request_id": str(uuid4()), "result": "inconclusive", "actual_result": "需要补充本轮验证",
             "reason_category": "recollection", "next_action": "重新采集"},
            format="json",
        ).status_code
        == 201
    )
    submitted = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "submit", "expected_version": plan["workflow_version"]},
        format="json",
    ).data
    session_client.force_authenticate(user=manager)
    returned = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "return", "expected_version": submitted["workflow_version"], "comment": "重新修复并采集"},
        format="json",
    )
    assert returned.status_code == 200 and returned.data["round_no"] == 2
    session_client.force_authenticate(user=tester)
    claimed = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "claim", "expected_version": returned.data["workflow_version"]},
        format="json",
    )
    assert claimed.status_code == 200
    no_new = session_client.post(
        base + f"items/{plan['items'][0]['id']}/executions/",
        {"request_id": str(uuid4()), "result": "passed", "actual_result": "旧证据不可代替本轮"},
        format="json",
    )
    assert no_new.status_code == 400


def test_plain_case_pass_cannot_close_daq_defect_without_data_manager_acceptance(session_client, data_flow):
    base, project, defect, *_ = data_flow
    response = session_client.patch(
        base + f"defects/{defect.id}/",
        {"status": "closed", "verification_method": "manual", "verification_note": "不应跳过DAQ新数据"},
        format="json",
    )
    assert response.status_code == 400


def test_approval_rechecks_evidence_authority_and_rejects_data_reassigned(session_client, data_flow, mocker):
    base, project, defect, solution, tester, manager = data_flow
    regression, plan = start(session_client, data_flow)
    upstream = mocker.patch("plane.quality.platform.fetch", return_value=authoritative_context())
    assert (
        session_client.post(
            base + f"plans/{plan['id']}/data-evidence/", {"source_session_id": "new-session"}, format="json"
        ).status_code
        == 201
    )
    assert (
        session_client.post(
            base + f"items/{plan['items'][0]['id']}/executions/",
            {"request_id": str(uuid4()), "result": "passed", "actual_result": "正常", "evidence": "新数据检查正常"},
            format="json",
        ).status_code
        == 201
    )
    submitted = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "submit", "expected_version": plan["workflow_version"]},
        format="json",
    ).data
    upstream.return_value = authoritative_context(projectId=999)
    session_client.force_authenticate(user=manager)
    response = session_client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": "approve", "expected_version": submitted["workflow_version"]},
        format="json",
    )
    assert response.status_code == 400
    defect.refresh_from_db()
    assert defect.status == "resolved"


def test_failed_regression_returns_to_repair_and_preserves_failed_plan(session_client, data_flow):
    base, project, defect, solution, tester, manager = data_flow
    _, plan = start(session_client, data_flow)
    response = session_client.post(base + f"items/{plan['items'][0]['id']}/executions/", {
        "request_id": str(uuid4()), "result": "failed", "actual_result": "连接仍然失败", "evidence": "本轮故障日志",
    }, format="json")
    assert response.status_code == 201
    submitted = session_client.post(base + f"plans/{plan['id']}/workflow/", {
        "action": "submit", "expected_version": plan["workflow_version"],
    }, format="json")
    assert submitted.status_code == 200
    assert submitted.data["status"] == "failed"
    defect.refresh_from_db()
    assert defect.status == "open" and defect.resolved_at is None
    assert defect.events.filter(note__contains="回归失败").exists()
    assert session_client.get(base + f"plans/{plan['id']}/").data["summary"]["failed"] == 1


@pytest.mark.parametrize("reason", ["recollection", "environment", "other"])
def test_inconclusive_retains_resolved_defect_and_blocks_approval(session_client, data_flow, reason):
    base, project, defect, solution, tester, manager = data_flow
    _, plan = start(session_client, data_flow)
    url = base + f"items/{plan['items'][0]['id']}/executions/"
    response = session_client.post(url, {
        "request_id": str(uuid4()), "result": "inconclusive", "actual_result": "数据不足，不能判断修复效果",
        "reason_category": reason, "next_action": "补充采集并核对环境后重新验证",
    }, format="json")
    assert response.status_code == 201, response.content
    assert response.data["reason_category"] == reason
    assert response.data["next_action"] == "补充采集并核对环境后重新验证"
    submitted = session_client.post(base + f"plans/{plan['id']}/workflow/", {
        "action": "submit", "expected_version": plan["workflow_version"],
    }, format="json")
    assert submitted.status_code == 200, submitted.content
    assert submitted.data["status"] == "review"
    assert submitted.data["summary"]["inconclusive"] == 1
    assert submitted.data["summary"]["failed"] == 0
    assert submitted.data["summary"]["blocked"] == 0
    assert submitted.data["summary"]["executed"] == 1
    defect.refresh_from_db()
    assert defect.status == "resolved"
    assert not defect.events.filter(note__contains="回归失败").exists()
    assert session_client.post(base + f"executions/{response.data['id']}/defect/", {}, format="json").status_code == 400
    session_client.force_authenticate(user=manager)
    rejected = session_client.post(base + f"plans/{plan['id']}/workflow/", {
        "action": "approve", "expected_version": submitted.data["workflow_version"], "comment": "确认结果",
    }, format="json")
    assert rejected.status_code == 400
    summary = session_client.get(base + "report/")
    assert summary.status_code == 200, summary.content
    assert summary.data["summary"]["inconclusive"] == 1
    assert summary.data["summary"]["pass_rate"] == 0
    assert session_client.get(base + "executions/?result=inconclusive").data["count"] == 1


@pytest.mark.parametrize("extra", [{}, {"reason_category": "other"}, {"next_action": "补采"}, {"reason_category": "invalid", "next_action": "补采"}])
def test_inconclusive_requires_reason_and_next_action(session_client, data_flow, extra):
    base, *_ = data_flow
    _, plan = start(session_client, data_flow)
    response = session_client.post(base + f"items/{plan['items'][0]['id']}/executions/", {
        "request_id": str(uuid4()), "result": "inconclusive", "actual_result": "无法判断", **extra,
    }, format="json")
    assert response.status_code == 400


def test_regression_request_freezes_optional_target_steps_environment_and_approved_verification(session_client, data_flow):
    base, project, defect, solution, tester, manager = data_flow
    details = {"devices": [{"name": "robot-a", "sensors": ["camera", "lidar"]}], "software": {"daq": "v2"}}
    steps = [{"action": "采集两轮", "expected": "日志和数据完整"}, {"action": "核对时间戳", "expected": "无跳变"}]
    response = session_client.post(base + f"defects/{defect.id}/data-regressions/", {
        "solution_id": str(solution.id), "environment": "复杂实验环境", "test_target": "核对连接恢复后的数据完整性",
        "verification_steps": steps, "environment_details": details,
    }, format="json")
    assert response.status_code == 201, response.content
    frozen = response.data["request_snapshot"]
    assert frozen["test_target"] == "核对连接恢复后的数据完整性"
    assert frozen["verification_steps"] == steps and frozen["environment_details"] == details
    assert frozen["approved_verification"] == "重新采集后检查日志和数据包"
    plan = response.data["plan"]
    assert plan["data_regression"]["request_snapshot"] == frozen
    assert plan["items"][0]["revision"]["snapshot"]["regression_request"] == frozen
    assert plan["items"][0]["revision"]["snapshot"]["steps"] == steps
    solution.verification = "后续改变不能覆盖审核内容"
    solution.save()
    reread = session_client.get(base + f"plans/{plan['id']}/")
    assert reread.data["data_regression"]["request_snapshot"] == frozen


@pytest.mark.parametrize("details", [["invalid"], "not an object", {"value": "x" * 21000}])
def test_regression_rejects_invalid_structured_environment(session_client, data_flow, details):
    base, project, defect, solution, *_ = data_flow
    response = session_client.post(base + f"defects/{defect.id}/data-regressions/", {
        "solution_id": str(solution.id), "environment": "本地", "environment_details": details,
    }, format="json")
    assert response.status_code == 400



def test_inconclusive_is_retained_in_saved_export_delivery_and_period_report(session_client, data_flow):
    from plane.quality.models import SavedReport
    from plane.quality.report_delivery import report_text
    base, project, defect, solution, tester, manager = data_flow
    _, plan = start(session_client, data_flow)
    result = session_client.post(base + f"items/{plan['items'][0]['id']}/executions/", {
        "request_id": str(uuid4()), "result": "inconclusive", "actual_result": "缺少足够样本",
        "reason_category": "recollection", "next_action": "补充两轮采集",
    }, format="json")
    assert result.status_code == 201, result.content
    session_client.force_authenticate(user=manager)
    report = session_client.post(base + "reports/", {
        "name": "无法判定回归报告", "plan_id": plan["id"], "request_id": str(uuid4()),
    }, format="json")
    assert report.status_code == 201, report.content
    assert report.data["snapshot"]["summary"]["inconclusive"] == 1
    exported = session_client.get(base + f"reports/{report.data['id']}/download/")
    assert exported.status_code == 200
    assert "无法判定" in exported.content.decode()
    assert "补充两轮采集" in exported.content.decode()
    assert "需要补采" in exported.content.decode()
    assert "无法判定 1" in report_text(SavedReport.objects.get(pk=report.data["id"]))
    from zoneinfo import ZoneInfo
    today = timezone.localtime(timezone.now(),ZoneInfo("Asia/Shanghai")).date().isoformat()
    period = session_client.get(base + f"project-report/?timezone=UTC&start={today}&end={today}&result=inconclusive")
    assert period.status_code == 200, period.content
    assert period.data["test_results"]["inconclusive"] == 1


def test_old_regression_request_defaults_and_permissions_are_preserved(session_client, data_flow):
    base, project, defect, solution, tester, manager = data_flow
    session_client.force_authenticate(user=tester)
    payload = {"solution_id": str(solution.id), "environment": "本地验证"}
    assert session_client.post(base + f"defects/{defect.id}/data-regressions/", payload, format="json").status_code == 403
    session_client.force_authenticate(user=manager)
    regression, plan = start(session_client, data_flow)
    frozen = regression["request_snapshot"]
    assert frozen["test_target"] == "" and frozen["environment_details"] == {}
    assert frozen["verification_steps"][0]["expected"] == "重新采集后检查日志和数据包"
    session_client.force_authenticate(user=manager)
    result = session_client.post(base + f"items/{plan['items'][0]['id']}/executions/", {
        "request_id": str(uuid4()), "result": "inconclusive", "actual_result": "无法判断",
        "reason_category": "environment", "next_action": "恢复环境",
    }, format="json")
    assert result.status_code == 403


def test_inconclusive_step_cannot_be_overall_passed(session_client, data_flow):
    base, *_ = data_flow
    _, plan = start(session_client, data_flow)
    result = session_client.post(base + f"items/{plan['items'][0]['id']}/executions/", {
        "request_id": str(uuid4()), "result": "passed", "actual_result": "无法判断",
        "reason_category": "environment", "next_action": "恢复环境",
        "step_results": [{"result": "inconclusive", "actual": "环境波动"}],
    }, format="json")
    assert result.status_code == 400
