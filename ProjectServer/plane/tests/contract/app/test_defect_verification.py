"""A reusable case definition never shares execution state between defects."""

from uuid import uuid4

import pytest
from django.utils import timezone
from plane.db.models import Project, ProjectMember, User, WorkspaceMember
from plane.quality.models import Defect

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def verification(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="验证隔离", identifier="VI")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    tester = User.objects.create(email="verify@test.local", username="verify-tester")
    WorkspaceMember.objects.create(workspace=workspace, member=tester, role=15)
    ProjectMember.objects.create(project=project, member=tester, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    cases = [
        session_client.post(
            base + "cases/",
            {"title": f"场景{i}", "steps": [{"action": "操作", "expected": "成功"}]},
            format="json",
        ).data
        for i in range(2)
    ]
    defects = [
        Defect.objects.create(
            project=project,
            created_by=create_user,
            title=f"缺陷{i}",
            status="resolved",
            fixed_build="v2",
            resolved_at=timezone.now(),
        )
        for i in range(2)
    ]
    return base, cases, defects, tester, create_user


def configure(client, base, defect, cases=None, **extra):
    defect.refresh_from_db()
    payload = {
        "expected_version": defect.edit_version,
        "request_id": str(uuid4()),
        "mode": "cases" if cases else "manual",
        "fixed_build": "v2",
        "environment": "测试环境",
    }
    payload.update(
        {"case_ids": [c["id"] for c in cases]} if cases else {"steps": [{"action": "操作", "expected": "成功"}]}
    )
    if "assignee_id" not in extra:
        tester = ProjectMember.objects.filter(project=defect.project, role=15).exclude(member=defect.created_by).first()
        if tester:
            extra["assignee_id"] = str(tester.member_id)
    if "assignee_id" not in extra:
        tester = ProjectMember.objects.filter(project=defect.project, role=15).exclude(member=defect.created_by).first()
        if tester:
            extra["assignee_id"] = str(tester.member_id)
    return client.post(base + f"defects/{defect.id}/verification/", {**payload, **extra}, format="json")


def workflow(client, base, defect, current, action, **extra):
    return client.post(
        base + f"defects/{defect.id}/verification/workflow/",
        {"expected_version": current["version"], "request_id": str(uuid4()), "action": action, **extra},
        format="json",
    )


def execute(client, base, item, expected_version, result="passed"):
    endpoint = (
        f"verification/cases/{item['item_id']}/executions/"
        if item.get("source") in {"library", "round"}
        else f"items/{item['item_id']}/executions/"
    )
    return client.post(
        base + endpoint,
        {
            "expected_version": expected_version,
            "request_id": str(uuid4()),
            "result": result,
            "actual_result": "实测结果",
            "evidence": "现场截图",
            "step_results": [{"result": result, "actual": "实测步骤"}],
        },
        format="json",
    )


def test_multiple_case_results_do_not_cross_defects_and_legacy_close_is_gated(session_client, verification):
    base, cases, defects, tester, manager = verification
    a = configure(session_client, base, defects[0], cases)
    assert a.status_code == 201, a.content
    a = a.data["current"]
    b = configure(session_client, base, defects[1], cases).data["current"]
    assert a["plan_id"] != b["plan_id"]
    session_client.force_authenticate(tester)
    first_execution = execute(session_client, base, a["items"][0], a["version"])
    assert first_execution.status_code == 201
    a = first_execution.data["current"]
    assert workflow(session_client, base, defects[0], a, "submit").status_code == 400
    second_execution = execute(session_client, base, a["items"][1], a["version"])
    assert second_execution.status_code == 201
    a = second_execution.data["current"]
    a = workflow(session_client, base, defects[0], a, "submit").data["current"]
    assert workflow(session_client, base, defects[0], a, "accept").status_code == 403
    session_client.force_authenticate(manager)
    bypass = session_client.patch(
        base + f"defects/{defects[0].id}/",
        {"status": "closed", "verification_method": "manual", "verification_note": "绕过"},
        format="json",
    )
    assert bypass.status_code == 409
    assert (
        session_client.post(
            base + f"defects/{defects[0].id}/disposition/",
            {"expected_version": 2, "kind": "not_a_bug", "reason": "绕过"},
            format="json",
        ).status_code
        == 409
    )
    accepted = workflow(session_client, base, defects[0], a, "accept", comment="验收通过")
    assert accepted.status_code == 200, accepted.content
    assert accepted.data["current"]["status"] == "accepted"
    defects[0].refresh_from_db()
    assert defects[0].status == "closed"
    b = session_client.get(base + f"defects/{defects[1].id}/verification/").data["current"]
    assert b["summary"]["pending"] == 2
    assert workflow(session_client, base, defects[1], b, "accept").status_code == 409


def test_manual_results_retest_reopen_and_actor_audit(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    response = configure(session_client, base, defect)
    assert response.status_code == 201, response.content
    current = response.data["current"]
    url = base + f"defects/{defect.id}/verification/result/"
    payload = {
        "expected_version": current["version"],
        "request_id": str(uuid4()),
        "result": "passed",
        "actual_result": "结果符合",
        "evidence": "截图",
        "step_results": [{"result": "passed", "actual": "操作成功"}],
    }
    session_client.force_authenticate(tester)
    recorded = session_client.post(url, payload, format="json")
    assert recorded.status_code == 201, recorded.content
    assert session_client.post(url, payload, format="json").status_code == 200
    current = recorded.data["current"]
    current = workflow(session_client, base, defect, current, "submit").data["current"]
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defect, current, "return_test").status_code == 400
    returned = workflow(session_client, base, defect, current, "return_test", comment="补测")
    assert returned.status_code == 200, returned.content
    new = returned.data["current"]
    assert new["round_no"] == 2 and new["summary"]["pending"] == 1
    assert session_client.post(url, payload, format="json").status_code == 403
    session_client.force_authenticate(tester)
    assert workflow(session_client, base, defect, new, "submit").status_code == 400
    payload.update(expected_version=new["version"], request_id=str(uuid4()))
    new = session_client.post(url, payload, format="json").data["current"]
    new = workflow(session_client, base, defect, new, "submit").data["current"]
    session_client.force_authenticate(manager)
    new = workflow(session_client, base, defect, new, "accept").data["current"]
    assert workflow(session_client, base, defect, new, "reopen").status_code == 400
    reopened = workflow(session_client, base, defect, new, "reopen", comment="发现遗漏")
    assert reopened.status_code == 200, reopened.content
    defect.refresh_from_db()
    assert defect.status == "open"
    assert reopened.data["history"][0]["manual_results"][0]["created_by_id"] == str(tester.id)
    assert reopened.data["history"][0]["manual_results"][0]["created_by_name"] == (
        tester.display_name or tester.username
    )
    assert defect.events.filter(created_by=manager, note__contains="发现遗漏").exists()


def test_tester_cannot_arrange_reassign_or_claim_a_verification(session_client, verification):
    from plane.quality.models import BusinessRole, ProjectRolePolicy

    base, _, defects, tester, manager = verification
    configured = configure(session_client, base, defects[0]).data["current"]
    ProjectRolePolicy.objects.create(project=defects[0].project, enabled=True)
    BusinessRole.objects.create(project=defects[0].project, created_by=manager, user=manager, role="PROJECT_MANAGER")
    BusinessRole.objects.create(project=defects[0].project, created_by=manager, user=tester, role="REGRESSION_TESTER")
    session_client.force_authenticate(tester)
    forbidden_arrangement = session_client.post(
        base + f"defects/{defects[0].id}/verification/",
        {
            "expected_version": defects[0].edit_version,
            "request_id": str(uuid4()),
            "mode": "manual",
            "fixed_build": "v2",
            "environment": "测试环境",
            "steps": [{"action": "操作", "expected": "成功"}],
            "assignee_id": str(tester.id),
        },
        format="json",
    )
    assert forbidden_arrangement.status_code == 403
    detail = session_client.get(base + f"defects/{defects[0].id}/verification/")
    assert detail.status_code == 200
    assert "can_claim" not in detail.data["current"]
    assert detail.data["current"]["can_record"]
    assert (
        workflow(session_client, base, defects[0], configured, "claim").status_code
        == 403
    )
    assert workflow(
        session_client,
        base,
        defects[0],
        configured,
        "assign",
        assignee_id=str(tester.id),
    ).status_code == 403


def test_verification_requires_test_assignee_and_cannot_be_unassigned(session_client, verification):
    base, _, defects, tester, manager = verification
    defect = defects[0]
    missing = configure(session_client, base, defect, assignee_id=None)
    assert missing.status_code == 400, missing.content
    configured = configure(session_client, base, defect, assignee_id=str(tester.id)).data["current"]
    unassigned = workflow(session_client, base, defect, configured, "assign", assignee_id=None)
    assert unassigned.status_code == 400, unassigned.content


def test_unassigned_verification_todo_is_for_arrangers_not_testers(session_client, verification):
    base, _, defects, tester, manager = verification
    configured = configure(session_client, base, defects[0], assignee_id=str(tester.id)).data["current"]
    from plane.quality.models import TestPlan

    TestPlan.objects.filter(pk=configured["plan_id"]).update(assignee=None)
    todo_url = "/api/quality-auth/my-todos/"
    session_client.force_authenticate(tester)
    tester_todos = session_client.get(todo_url, {"workspace": defects[0].project.workspace.slug, "kind": "plan"})
    assert tester_todos.status_code == 200
    assert not any(item["id"] == configured["plan_id"] for item in tester_todos.data["results"])
    session_client.force_authenticate(manager)
    manager_todos = session_client.get(todo_url, {"workspace": defects[0].project.workspace.slug, "kind": "plan"})
    assert manager_todos.status_code == 200
    row = next(item for item in manager_todos.data["results"] if item["id"] == configured["plan_id"])
    assert row["next_action"] == "安排测试"
    assert row["responsibility"] == "安排"


def test_case_regression_can_start_from_requirements_and_add_private_round_case(session_client, verification):
    from plane.quality.models import TestCase

    base, _, defects, tester, manager = verification
    defect = defects[0]
    response = session_client.post(
        base + f"defects/{defect.id}/verification/",
        {
            "expected_version": defect.edit_version,
            "request_id": str(uuid4()),
            "mode": "cases",
            "fixed_build": "v2",
            "environment": "测试环境",
            "test_requirements": "检查启动页和数据保存结果",
            "assignee_id": str(tester.id),
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    current = response.data["current"]
    assert current["items"] == [] and current["summary"]["total"] == 0
    assert current["execution_state"] == "needs_cases"
    assert current["test_requirements"] == "检查启动页和数据保存结果"
    session_client.force_authenticate(tester)
    added = session_client.post(
        base + f"defects/{defect.id}/verification/cases/",
        {
            "expected_version": current["version"],
            "request_id": str(uuid4()),
            "case_ids": [],
            "temporary_cases": [
                {"title": "本轮临时检查", "preconditions": "测试环境已启动", "steps": [{"action": "检查数据写入", "expected": "数据可读取"}]}
            ],
        },
        format="json",
    )
    assert added.status_code == 201, added.content
    current = added.data["current"]
    assert current["execution_state"] == "pending"
    assert current["summary"]["total"] == 1
    item = current["items"][0]
    assert item["source"] == "round" and item["title"] == "本轮临时检查"
    executed = session_client.post(
        base + f"verification/cases/{item['item_id']}/executions/",
        {
            "expected_version": current["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": "数据可读取",
            "step_results": [{"result": "passed", "actual": "数据可读取"}],
        },
        format="json",
    )
    assert executed.status_code == 201, executed.content
    assert executed.data["current"]["summary"]["passed"] == 1
    assert not TestCase.objects.filter(project=defect.project, title="本轮临时检查").exists()


def test_round_case_execution_requires_version_and_rejects_stale_submit(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    current = configure(session_client, base, defect, cases).data["current"]
    session_client.force_authenticate(tester)
    item = current["items"][0]
    endpoint = base + f"verification/cases/{item['item_id']}/executions/"
    payload = {
        "request_id": str(uuid4()),
        "result": "passed",
        "actual_result": "实测正常",
        "step_results": [{"result": "passed", "actual": "实测正常"}],
    }
    missing = session_client.post(endpoint, payload, format="json")
    assert missing.status_code == 400, missing.content
    stale = session_client.post(endpoint, {**payload, "expected_version": current["version"] + 1}, format="json")
    assert stale.status_code == 409, stale.content
    valid_payload = {**payload, "expected_version": current["version"]}
    accepted = session_client.post(endpoint, valid_payload, format="json")
    assert accepted.status_code == 201, accepted.content
    retry = session_client.post(endpoint, valid_payload, format="json")
    assert retry.status_code == 200, retry.content
    from plane.quality.models import DefectVerificationCaseExecution

    assert DefectVerificationCaseExecution.objects.filter(item_id=item["item_id"]).count() == 1


def test_legacy_plan_snapshot_keeps_source_item_and_execution_links(session_client, verification):
    from plane.quality.defect_verification import snapshot_legacy_plan_items
    from plane.quality.models import (
        DefectVerificationCase,
        DefectVerificationCaseExecution,
        PlanItem,
        TestCase,
        TestExecution,
    )

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    current = configure(session_client, base, defect, cases).data["current"]
    row = defect.verification_rounds.get(pk=current["id"])
    row.case_items.all().delete()
    source_case = TestCase.objects.get(pk=cases[0]["id"])
    source_revision = source_case.revisions.get(version=source_case.version)
    plan_item = PlanItem.objects.create(
        project=defect.project,
        created_by=manager,
        plan=row.plan,
        case=source_case,
        revision=source_revision,
    )
    legacy = TestExecution.objects.create(
        project=defect.project,
        created_by=tester,
        item=plan_item,
        request_id=uuid4(),
        result="passed",
        actual_result="旧计划实测正常",
        evidence="旧证据",
        step_results=[],
        round_no=row.round_no,
    )
    snapshot_legacy_plan_items(row, manager)
    frozen = DefectVerificationCase.objects.get(verification=row)
    copied = DefectVerificationCaseExecution.objects.get(item=frozen)
    assert frozen.source_plan_item_id == plan_item.id
    assert copied.source_execution_id == legacy.id
    assert copied.created_by_id == legacy.created_by_id
    assert TestExecution.objects.filter(pk=legacy.pk).exists()
    snapshot_legacy_plan_items(row, manager)
    assert DefectVerificationCase.objects.filter(verification=row).count() == 1
    assert DefectVerificationCaseExecution.objects.filter(item=frozen).count() == 1


def test_any_project_member_can_add_reusable_case_without_case_management_role(session_client, verification):
    from plane.quality.models import BusinessRole, ProjectRolePolicy

    base, _, defects, tester, manager = verification
    project = defects[0].project
    ProjectRolePolicy.objects.create(project=project, enabled=True)
    BusinessRole.objects.create(project=project, created_by=manager, user=manager, role="PROJECT_MANAGER")
    contributor = User.objects.create(email="case-contributor@test.local", username="case-contributor")
    WorkspaceMember.objects.create(workspace=project.workspace, member=contributor, role=15)
    ProjectMember.objects.create(project=project, member=contributor, role=15)
    session_client.force_authenticate(contributor)
    response = session_client.post(
        base + "cases/",
        {"title": "成员新增用例", "steps": [{"action": "操作", "expected": "完成"}]},
        format="json",
    )
    assert response.status_code == 201, response.content
    session_client.force_authenticate(contributor)
    edited = session_client.patch(
        base + f"cases/{response.data['id']}/",
        {"expected_version": response.data["version"], "title": "无管理权限不可编辑"},
        format="json",
    )
    assert edited.status_code == 403


def test_admin_can_execute_one_of_ten_cases_without_reassigning_tester(session_client, verification):
    from plane.license.models import Instance, InstanceAdmin
    from plane.quality.models import DefectVerificationCaseExecution
    from plane.db.models import Notification

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    project = defect.project
    configured = configure(session_client, base, defect, cases, assignee_id=str(tester.id))
    assert configured.status_code == 201, configured.content
    current = configured.data["current"]
    # Add nine more frozen library cases to make the remaining-work rule observable.
    extra = [
        session_client.post(
            base + "cases/",
            {"title": f"第{i}条检查", "steps": [{"action": "检查", "expected": "正常"}]},
            format="json",
        ).data
        for i in range(3, 11)
    ]
    added = session_client.post(
        base + f"defects/{defect.id}/verification/cases/",
        {
            "expected_version": current["version"],
            "request_id": str(uuid4()),
            "case_ids": [row["id"] for row in extra],
            "temporary_cases": [],
        },
        format="json",
    )
    assert added.status_code == 201, added.content
    current = added.data["current"]
    assert current["summary"]["total"] == 10
    administrator = User.objects.create(username="verification-proxy-admin", email="verification-proxy-admin@test.invalid")
    instance = Instance.objects.create(
        instance_name="验证",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    InstanceAdmin.objects.create(instance=instance, user=administrator)
    session_client.force_authenticate(administrator)
    item = current["items"][0]
    response = session_client.post(
        base + f"verification/cases/{item['item_id']}/executions/",
        {
            "expected_version": current["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": "管理员代测正常",
            "step_results": [{"result": "passed", "actual": "管理员代测正常"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    refreshed = response.data["current"]
    assert refreshed["assignee_id"] == str(tester.id)
    assert refreshed["summary"]["passed"] == 1
    assert refreshed["summary"]["pending"] == 9
    execution = DefectVerificationCaseExecution.objects.get(item_id=item["item_id"])
    assert execution.created_by_id == administrator.id
    assert Notification.objects.filter(receiver=tester, entity_identifier=current["plan_id"]).exists()
    owner_stats = session_client.get(
        base + "owner-statistics/",
        {
            "source": "quality",
            "metric": "summary_passed",
            "verification_id": current["id"],
            "per_page": 20,
        },
    )
    assert owner_stats.status_code == 200, owner_stats.content
    assert any(row["owner_id"] == str(administrator.id) and row["count"] == 1 for row in owner_stats.data["results"])
    session_client.force_authenticate(tester)
    todo = session_client.get("/api/quality-auth/my-todos/", {"workspace": project.workspace.slug, "kind": "plan"})
    assert todo.status_code == 200
    row = next(item for item in todo.data["results"] if item["id"] == str(current["plan_id"]))
    assert row["next_action"] == "执行用例"


def test_new_build_and_case_revision_invalidate_old_pass_and_plan_is_immutable(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    configured = configure(session_client, base, defect, cases)
    assert configured.status_code == 201, configured.content
    current = configured.data["current"]
    session_client.force_authenticate(tester)
    for item in current["items"]:
        execution = execute(session_client, base, item, current["version"])
        assert execution.status_code == 201
        current = execution.data["current"]
    assert (
        session_client.patch(
            base + f"plans/{current['plan_id']}/", {"expected_version": 1, "build": "fake"}, format="json"
        ).status_code
        == 409
    )
    current = workflow(session_client, base, defect, current, "submit").data["current"]
    assert execute(session_client, base, current["items"][0], current["version"], "failed").status_code == 409
    session_client.force_authenticate(manager)
    changed = session_client.patch(
        base + f"cases/{cases[0]['id']}/", {"expected_version": 1, "title": "新版本"}, format="json"
    )
    assert changed.status_code == 200
    assert workflow(session_client, base, defect, current, "accept").status_code == 409
    assert workflow(session_client, base, defect, current, "return_repair", comment="重修").status_code == 200
    defect.refresh_from_db()
    assert defect.status == "open"
    listed = session_client.get(base + "verification-results/")
    assert listed.status_code == 200 and listed.data["results"][0]["defect_id"] == str(defect.id)
    assert listed.data["results"][0]["code"] == defect.code
    assert session_client.get(base + "verification-results/", {"search": defect.code}).data["count"] == 1
    assert session_client.get(base + "verification-results/", {"search": "不存在"}).data["count"] == 0


def test_preconfigure_actual_execution_latest_result_and_build_change(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    defect.status, defect.fixed_build, defect.resolved_at = "open", "", None
    defect.save()
    response = configure(session_client, base, defect, cases)
    assert response.status_code == 201, response.content
    current = response.data["current"]
    assert not current["can_record"] and current["can_configure"]
    assert configure(session_client, base, defect, cases).data["current"]["id"] == current["id"]
    session_client.force_authenticate(tester)
    assert execute(session_client, base, current["items"][0], current["version"]).status_code == 409
    session_client.force_authenticate(manager)
    resolved = session_client.patch(
        base + f"defects/{defect.id}/", {"status": "resolved", "fixed_build": "v2"}, format="json"
    )
    assert resolved.status_code == 200, resolved.content
    session_client.force_authenticate(tester)
    for item in current["items"]:
        execution = execute(session_client, base, item, current["version"])
        assert execution.status_code == 201
        current = execution.data["current"]
    failed = execute(session_client, base, current["items"][0], current["version"], "failed")
    assert failed.status_code == 201
    current = failed.data["current"]
    current = workflow(session_client, base, defect, current, "submit").data["current"]
    assert current["summary"]["failed"] == 1
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defect, current, "accept").status_code == 400
    defect.fixed_build = "v3"
    defect.save()
    assert workflow(session_client, base, defect, current, "accept").status_code == 409


def test_configure_changes_create_round_keep_evidence_and_stale_versions_fail(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    first = configure(session_client, base, defect).data["current"]
    response = configure(session_client, base, defect, cases)
    assert response.status_code == 201, response.content
    assert response.data["current"]["round_no"] == 2
    assert response.data["history"][0]["steps"] == first["steps"]
    stale = session_client.post(
        base + f"defects/{defect.id}/verification/",
        {
            "expected_version": 1,
            "request_id": str(uuid4()),
            "mode": "manual",
            "fixed_build": "v2",
            "environment": "环境",
            "steps": [{"action": "操作", "expected": "结果"}],
        },
        format="json",
    )
    assert stale.status_code == 409
    assert workflow(session_client, base, defect, first, "submit").status_code == 409


def test_manual_requirements_can_be_updated_before_results_but_not_rewrite_executed_round(session_client, verification):
    from plane.quality.models import DefectVerification, DefectVerificationEvent, DefectVerificationResult

    base, _, defects, tester, manager = verification
    defect = defects[0]
    current = configure(session_client, base, defect, assignee_id=str(tester.id)).data["current"]
    response = configure(
        session_client,
        base,
        defect,
        assignee_id=str(tester.id),
        steps=[{"action": "新增检查要求", "expected": "页面可打开"}],
    )
    assert response.status_code == 200, response.content
    current = response.data["current"]
    assert current["round_no"] == 1
    assert current["steps"] == [{"action": "新增检查要求", "expected": "页面可打开"}]
    assert DefectVerification.objects.filter(defect=defect).count() == 1
    assert DefectVerificationEvent.objects.filter(verification_id=current["id"], action="requirements_updated").exists()
    session_client.force_authenticate(tester)
    recorded = session_client.post(
        base + f"defects/{defect.id}/verification/result/",
        {
            "expected_version": current["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "actual_result": "页面可打开",
            "step_results": [{"result": "passed", "actual": "页面可打开"}],
        },
        format="json",
    )
    assert recorded.status_code == 201, recorded.content
    session_client.force_authenticate(manager)
    changed = configure(
        session_client,
        base,
        defect,
        assignee_id=str(tester.id),
        steps=[{"action": "覆盖已测要求", "expected": "不同"}],
    )
    assert changed.status_code == 409
    assert DefectVerificationResult.objects.filter(verification_id=current["id"]).count() == 1


def test_strict_business_duties_and_readonly_boundaries(session_client, verification):
    from plane.quality.models import BusinessRole, ProjectRolePolicy

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    ProjectRolePolicy.objects.create(project=defect.project, enabled=True)
    BusinessRole.objects.create(project=defect.project, created_by=manager, user=manager, role="PROJECT_MANAGER")
    BusinessRole.objects.create(project=defect.project, created_by=manager, user=tester, role="TECHNICIAN")
    execution_tester = User.objects.create(email="strict-tester@test.local", username="strict-tester")
    WorkspaceMember.objects.create(workspace=defect.project.workspace, member=execution_tester, role=15)
    ProjectMember.objects.create(project=defect.project, member=execution_tester, role=15)
    BusinessRole.objects.create(
        project=defect.project, created_by=manager, user=execution_tester, role="REGRESSION_TESTER"
    )
    session_client.force_authenticate(tester)
    response = configure(session_client, base, defect, assignee_id=str(execution_tester.id))
    assert response.status_code == 201, response.content
    current = response.data["current"]
    manual_url = base + f"defects/{defect.id}/verification/result/"
    result = {
        "expected_version": current["version"],
        "request_id": str(uuid4()),
        "result": "passed",
        "actual_result": "现场成功",
        "evidence": "截图",
        "step_results": [{"result": "passed", "actual": "成功"}],
    }
    assert session_client.post(manual_url, result, format="json").status_code == 403
    session_client.force_authenticate(execution_tester)
    response = session_client.post(manual_url, result, format="json")
    assert response.status_code == 201, response.content
    current = workflow(session_client, base, defect, response.data["current"], "submit").data["current"]
    assert workflow(session_client, base, defect, current, "accept").status_code == 403
    session_client.force_authenticate(manager)
    response = workflow(session_client, base, defect, current, "accept")
    assert response.status_code == 200, response.content
    ProjectMember.objects.filter(project=defect.project, member=manager).update(role=5)
    assert workflow(session_client, base, defect, response.data["current"], "reopen", comment="只读").status_code == 403


@pytest.mark.parametrize("readonly_scope", ["project", "workspace"])
def test_nonstrict_readonly_get_exposes_no_write_actions(session_client, verification, readonly_scope):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    configure(session_client, base, defect)
    configured = configure(session_client, base, defect, cases)
    assert configured.status_code == 201
    if readonly_scope == "project":
        ProjectMember.objects.filter(project=defect.project, member=tester).update(role=5)
    else:
        WorkspaceMember.objects.filter(workspace=defect.project.workspace, member=tester).update(role=5)
    session_client.force_authenticate(tester)
    response = session_client.get(base + f"defects/{defect.id}/verification/")
    assert response.status_code == 200
    rows = [response.data["current"], *response.data["history"]]
    assert len(rows) == 2
    for row in rows:
        assert all(not value for key, value in row.items() if key.startswith("can_")), row
    listed = session_client.get(base + "verification-results/")
    assert listed.status_code == 200
    assert not listed.data["results"][0]["current"]["can_configure"]


@pytest.mark.django_db(transaction=True)
def test_concurrent_manual_result_has_one_winner(session_client, verification):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from rest_framework.test import APIClient
    from plane.quality.models import DefectVerificationResult

    base, cases, defects, tester, manager = verification
    defect = defects[0]
    current = configure(session_client, base, defect).data["current"]

    def submit(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(tester)
            response = client.post(
                base + f"defects/{defect.id}/verification/result/",
                {
                    "expected_version": current["version"],
                    "request_id": str(uuid4()),
                    "result": "passed",
                    "actual_result": "成功",
                    "evidence": "截图",
                    "step_results": [{"result": "passed", "actual": "成功"}],
                },
                format="json",
            )
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [201, 409]
    assert DefectVerificationResult.objects.filter(verification__defect=defect).count() == 1


def test_manual_and_case_steps_need_no_duplicate_summary_or_evidence(session_client, verification):
    base, cases, defects, tester, manager = verification
    manual = configure(session_client, base, defects[0]).data["current"]
    session_client.force_authenticate(tester)
    response = session_client.post(
        base + f"defects/{defects[0].id}/verification/result/",
        {
            "expected_version": manual["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "step_results": [{"result": "passed", "actual": "逐步验证正常"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    current = workflow(session_client, base, defects[0], response.data["current"], "submit").data["current"]
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defects[0], current, "accept").status_code == 200
    selected = configure(session_client, base, defects[1], cases).data["current"]
    session_client.force_authenticate(tester)
    response = execute(session_client, base, selected["items"][0], selected["version"])
    assert response.status_code == 201, response.data
    incomplete = session_client.post(
        base + f"verification/cases/{selected['items'][1]['item_id']}/executions/",
        {
            "expected_version": response.data["current"]["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "step_results": [{"result": "passed", "actual": ""}],
        },
        format="json",
    )
    assert incomplete.status_code == 400


@pytest.mark.parametrize("mode", ["manual", "cases"])
def test_verification_task_owner_queue_and_result_share_one_round(session_client, verification, mode):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    response = configure(session_client, base, defect, cases if mode == "cases" else None, assignee_id=str(tester.id))
    assert response.status_code == 201, response.content
    row = response.data["current"]
    assert row["plan_id"], "人工验证也需要现有测试任务入口"
    assert row["assignee_id"] == str(tester.id)
    session_client.force_authenticate(tester)
    task = session_client.get(base + f"plans/{row['plan_id']}/")
    assert task.status_code == 200, task.content
    assert task.data["verification"]["defect_id"] == str(defect.id)
    assert task.data["verification"]["mode"] == mode
    todos = session_client.get(
        "/api/quality-auth/my-todos/", {"workspace": defect.project.workspace.slug, "kind": "plan"}
    )
    assert any(item["id"] == row["plan_id"] for item in todos.data["results"]), todos.data
    if mode == "manual":
        recorded = session_client.post(
            base + f"defects/{defect.id}/verification/result/",
            {
                "expected_version": row["version"],
                "request_id": str(uuid4()),
                "result": "passed",
                "step_results": [{"result": "passed", "actual": "实测正常"}],
            },
            format="json",
        )
        assert recorded.status_code == 201, recorded.content
    else:
        for item in row["items"]:
            execution = execute(session_client, base, item, row["version"])
            assert execution.status_code == 201
            row = execution.data["current"]
    row = session_client.get(base + f"defects/{defect.id}/verification/").data["current"]
    task = session_client.get(base + f"plans/{row['plan_id']}/").data
    assert task["summary"]["passed"] == row["summary"]["passed"]
    row = workflow(session_client, base, defect, row, "submit").data["current"]
    task = session_client.get(base + f"plans/{row['plan_id']}/").data
    assert task["status"] == "review"
    assert task["verification"]["status"] == row["status"] == "review"
    session_client.force_authenticate(manager)
    accepted = workflow(session_client, base, defect, row, "accept")
    assert accepted.status_code == 200, accepted.content
    assert session_client.get(base + f"plans/{row['plan_id']}/").data["status"] == "completed"


def test_prearranged_task_explains_waiting_for_repair(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = defects[0]
    defect.status, defect.fixed_build, defect.resolved_at = "open", "", None
    defect.save()
    row = configure(session_client, base, defect, assignee_id=str(tester.id)).data["current"]
    assert row["execution_state"] == "waiting_repair"
    assert row["blocked_reason"] == "等待技术员修复"
    assert not row["can_record"]
    assert row["plan_id"]


def test_different_tester_cannot_overwrite_assigned_verification(session_client, verification):
    base, cases, defects, tester, manager = verification
    row = configure(session_client, base, defects[0], assignee_id=str(tester.id)).data["current"]
    other = User.objects.create(username="other-verifier", email="other-verifier@local.test")
    WorkspaceMember.objects.create(workspace=defects[0].project.workspace, member=other, role=15)
    ProjectMember.objects.create(project=defects[0].project, member=other, role=15)
    session_client.force_authenticate(other)
    response = session_client.post(
        base + f"defects/{defects[0].id}/verification/result/",
        {
            "expected_version": row["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "step_results": [{"result": "passed", "actual": "不能代填"}],
        },
        format="json",
    )
    assert response.status_code == 403, response.content


def test_assigned_manual_retest_keeps_owner_and_closure_removes_todo(session_client, verification):
    base, _, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, assignee_id=str(tester.id)).data["current"]
    session_client.force_authenticate(tester)

    def record(current, result):
        response = session_client.post(
            base + f"defects/{defect.id}/verification/result/",
            {
                "expected_version": current["version"],
                "request_id": str(uuid4()),
                "result": result,
                "step_results": [{"result": result, "actual": "实测"}],
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        return response.data["current"]

    row = record(row, "failed")
    assert row["execution_state"] == "tested"
    row = workflow(session_client, base, defect, row, "submit").data["current"]
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defect, row, "accept").status_code == 400
    old_plan = row["plan_id"]
    row = workflow(session_client, base, defect, row, "return_test", comment="补测失败步骤").data["current"]
    assert row["plan_id"] != old_plan and row["assignee_id"] == str(tester.id)
    assert session_client.get(base + f"plans/{old_plan}/").data["status"] == "cancelled"
    session_client.force_authenticate(tester)
    row = record(row, "passed")
    row = workflow(session_client, base, defect, row, "submit").data["current"]
    session_client.force_authenticate(manager)
    assert workflow(session_client, base, defect, row, "accept").status_code == 200
    session_client.force_authenticate(tester)
    todos = session_client.get(
        "/api/quality-auth/my-todos/", {"workspace": defect.project.workspace.slug, "kind": "plan"}
    )
    assert not any(item["id"] in {old_plan, row["plan_id"]} for item in todos.data["results"])


def test_global_administrator_can_execute_other_testers_round(session_client, verification):
    from plane.license.models import Instance, InstanceAdmin

    base, _, defects, tester, manager = verification
    row = configure(session_client, base, defects[0], assignee_id=str(tester.id)).data["current"]
    administrator = User.objects.create(username="verification-admin", email="verification-admin@test.invalid")
    instance = Instance.objects.create(
        instance_name="验证",
        instance_id=str(uuid4()),
        current_version="test",
        last_checked_at=timezone.now(),
        is_setup_done=True,
    )
    InstanceAdmin.objects.create(instance=instance, user=administrator)
    session_client.force_authenticate(administrator)
    detail = session_client.get(base + f"defects/{defects[0].id}/verification/")
    assert detail.status_code == 200 and detail.data["current"]["can_record"], detail.content
    response = session_client.post(
        base + f"defects/{defects[0].id}/verification/result/",
        {
            "expected_version": row["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "step_results": [{"result": "passed", "actual": "管理员代执行"}],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert response.data["current"]["manual_results"][0]["created_by_id"] == str(administrator.id)


def test_reassign_verification_moves_todos_and_rejects_stale_or_revoked_actor(session_client, verification):
    from plane.db.models import Notification

    base, _, defects, tester, manager = verification
    defect = defects[0]
    row = configure(session_client, base, defect, assignee_id=str(tester.id)).data["current"]
    second = User.objects.create(username="second-test", email="second-test@test.invalid")
    WorkspaceMember.objects.create(workspace=defect.project.workspace, member=second, role=15)
    ProjectMember.objects.create(project=defect.project, member=second, role=15)
    assigned = workflow(session_client, base, defect, row, "assign", assignee_id=str(second.id))
    assert assigned.status_code == 200, assigned.content
    assert assigned.data["current"]["assignee_id"] == str(second.id)
    assert Notification.objects.filter(receiver=second).exists()
    assert workflow(session_client, base, defect, row, "assign", assignee_id=str(tester.id)).status_code == 409
    session_client.force_authenticate(tester)
    assert not session_client.get(base + f"defects/{defect.id}/verification/").data["current"]["can_record"]
    todos_url = "/api/quality-auth/my-todos/"
    assert (
        session_client.get(todos_url, {"workspace": defect.project.workspace.slug, "kind": "plan"}).data["count"] == 0
    )
    session_client.force_authenticate(second)
    assert (
        session_client.get(todos_url, {"workspace": defect.project.workspace.slug, "kind": "plan"}).data["count"] == 1
    )
    ProjectMember.objects.filter(project=defect.project, member=second).update(is_active=False)
    response = session_client.post(
        base + f"defects/{defect.id}/verification/result/",
        {
            "expected_version": assigned.data["current"]["version"],
            "request_id": str(uuid4()),
            "result": "passed",
            "step_results": [{"result": "passed", "actual": "已失去权限"}],
        },
        format="json",
    )
    assert response.status_code == 403
