"""An approved repair proposal unlocks the defect's regression handoff."""
from uuid import uuid4

import pytest

from plane.db.models import ProjectMember, User, WorkspaceMember
from plane.quality.models import BusinessRole, ProjectRolePolicy, Defect
from plane.tests.contract.app.test_defect_verification import configure, verification, workflow

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def repair_flow(session_client, verification):
    base, cases, defects, tester, manager = verification
    defect = Defect.objects.create(project=defects[0].project, created_by=manager, title="新修复待审核")
    technician = User.objects.create(username="repair-owner", email="repair-owner@test.invalid")
    WorkspaceMember.objects.create(workspace=defect.project.workspace, member=technician, role=15)
    ProjectMember.objects.create(project=defect.project, member=technician, role=15)
    ProjectRolePolicy.objects.create(project=defect.project, enabled=True)
    for user, role in [(technician, "TECHNICIAN"), (manager, "PROJECT_MANAGER"), (tester, "REGRESSION_TESTER")]:
        BusinessRole.objects.create(project=defect.project, created_by=manager, user=user, role=role)
    reporter = User.objects.create(username="flow-reporter", email="flow-reporter@test.invalid")
    WorkspaceMember.objects.create(workspace=defect.project.workspace, member=reporter, role=15)
    ProjectMember.objects.create(project=defect.project, member=reporter, role=15)
    defect.created_by = reporter
    defect.status, defect.fixed_build, defect.resolved_at, defect.assignee = "in_progress", "", None, technician
    defect.save()
    session_client.force_authenticate(technician)
    return base, cases, defect, technician, tester, manager


def proposal(client, base, defect):
    response = client.post(base + "solutions/", {
        "defect_id": str(defect.pk), "title": "修复采集边界", "root_cause": "边界条件缺失",
        "steps": "补全边界检查后发布修复版本", "verification": "重现原操作并检查边界结果",
    }, format="json")
    assert response.status_code == 201, response.content
    return response.data


def submit(client, base, solution, manager):
    response = client.post(base + f"solutions/{solution['id']}/submit/", {
        "expected_version": solution["edit_version"], "reviewer_ids": [str(manager.pk)], "required_count": 1,
    }, format="json")
    assert response.status_code == 200, response.content
    return response.data


def approve(client, base, solution, manager):
    solution = submit(client, base, solution, manager)
    client.force_authenticate(manager)
    response = client.post(base + f"solutions/{solution['id']}/review/", {
        "revision_id": solution["current_revision_id"], "decision": "approve",
    }, format="json")
    assert response.status_code == 200, response.content
    return response.data


@pytest.mark.parametrize("state", ["missing", "draft", "review", "rejected"])
def test_unapproved_proposal_blocks_atomic_handoff_without_mutation(session_client, repair_flow, state):
    base, _, defect, technician, tester, manager = repair_flow
    if state != "missing":
        solution = proposal(session_client, base, defect)
        if state in {"review", "rejected"}:
            solution = submit(session_client, base, solution, manager)
        if state == "rejected":
            session_client.force_authenticate(manager)
            response = session_client.post(base + f"solutions/{solution['id']}/review/", {
                "revision_id": solution["current_revision_id"], "decision": "reject", "comment": "补全修复步骤",
            }, format="json")
            assert response.status_code == 200, response.content
            session_client.force_authenticate(technician)
    defect.refresh_from_db()
    version = defect.edit_version
    response = configure(session_client, base, defect, repair_and_arrange=True, repair_note="修复完成", assignee_id=str(tester.pk))
    assert response.status_code == 409, response.content
    assert "方案" in str(response.data)
    defect.refresh_from_db()
    assert defect.status == "in_progress" and defect.edit_version == version
    assert defect.fixed_build == "" and defect.resolved_at is None
    assert not defect.verification_rounds.exists()
    data = session_client.get(base + f"defects/{defect.pk}/verification/").data
    assert not data["can_configure"]
    assert data["solution_review"]["status"] == state
    assert data["solution_review"]["blocked_reason"]


@pytest.mark.parametrize("mode", ["manual", "cases"])
def test_approved_proposal_handoff_assigns_tester_and_enters_executable_round(session_client, repair_flow, mode):
    base, cases, defect, technician, tester, manager = repair_flow
    solution = approve(session_client, base, proposal(session_client, base, defect), manager)
    defect.refresh_from_db()
    assert defect.status == "in_progress"  # Review approval is not proof of repair completion.
    session_client.force_authenticate(technician)
    data = session_client.get(base + f"defects/{defect.pk}/verification/").data
    assert data["can_configure"]
    assert data["solution_review"]["status"] == "approved"
    assert data["solution_review"]["repair_note"] == solution["steps"]
    assert data["solution_review"]["test_requirements"] == solution["verification"]
    response = configure(session_client, base, defect, cases if mode == "cases" else None,
                         repair_and_arrange=True, repair_note=solution["steps"], assignee_id=str(tester.pk))
    assert response.status_code == 201, response.content
    assert response.data["defect_status"] == "resolved"
    session_client.force_authenticate(tester)
    row = session_client.get(base + f"defects/{defect.pk}/verification/").data["current"]
    assert row["can_record"] and row["assignee_id"] == str(tester.pk)
    if mode == "manual":
        recorded = session_client.post(base + f"defects/{defect.pk}/verification/result/", {
            "expected_version": row["version"], "request_id": str(uuid4()), "result": "passed",
            "actual_result": "按已审核方案验证通过", "step_results": [{"result": "passed", "actual": "通过"}],
        }, format="json")
        assert recorded.status_code == 201, recorded.content
        row = workflow(session_client, base, defect, recorded.data["current"], "submit").data["current"]
        session_client.force_authenticate(manager)
        assert workflow(session_client, base, defect, row, "accept").status_code == 200
        from plane.db.models import Notification
        assert Notification.objects.filter(receiver=defect.created_by, entity_identifier=str(defect.pk), title__contains="缺陷已验收关闭").exists()


def test_editing_approved_solution_blocks_stale_open_form_and_hides_record_action(session_client, repair_flow):
    base, _, defect, technician, tester, manager = repair_flow
    solution = approve(session_client, base, proposal(session_client, base, defect), manager)
    session_client.force_authenticate(technician)
    row = configure(session_client, base, defect, repair_and_arrange=True, repair_note=solution["steps"], assignee_id=str(tester.pk)).data["current"]
    changed = session_client.patch(base + f"solutions/{solution['id']}/", {
        "expected_version": solution["edit_version"], "steps": "需要重新审核的修复步骤",
    }, format="json")
    assert changed.status_code == 200, changed.content
    response = configure(session_client, base, defect, assignee_id=str(tester.pk))
    assert response.status_code == 409, response.content
    session_client.force_authenticate(tester)
    data = session_client.get(base + f"defects/{defect.pk}/verification/").data
    assert not data["current"]["can_record"]
    result = session_client.post(base + f"defects/{defect.pk}/verification/result/", {
        "expected_version": row["version"], "request_id": str(uuid4()), "result": "passed",
        "step_results": [{"result": "passed", "actual": "旧窗口提交"}],
    }, format="json")
    assert result.status_code == 409, result.content


def test_marking_new_defect_resolved_does_not_turn_it_into_legacy(session_client, repair_flow):
    base, _, defect, technician, tester, manager = repair_flow
    changed = session_client.patch(base + f"defects/{defect.pk}/", {
        "expected_version": defect.edit_version, "status": "resolved", "fixed_build": "v2",
    }, format="json")
    assert changed.status_code == 200, changed.content
    response = configure(session_client, base, defect, assignee_id=str(tester.pk))
    assert response.status_code == 409, response.content
    assert not defect.verification_rounds.exists()


@pytest.mark.parametrize("submitted", [False, True])
def test_new_approved_revision_requires_new_round_and_never_reuses_old_pass(session_client, repair_flow, submitted):
    base, _, defect, technician, tester, manager = repair_flow
    solution = approve(session_client, base, proposal(session_client, base, defect), manager)
    session_client.force_authenticate(technician)
    old_revision = solution["current_revision_id"]
    row = configure(session_client, base, defect, repair_and_arrange=True,
                    repair_note=solution["steps"], assignee_id=str(tester.pk)).data["current"]
    session_client.force_authenticate(tester)
    recorded = session_client.post(base + f"defects/{defect.pk}/verification/result/", {
        "expected_version": row["version"], "request_id": str(uuid4()), "result": "passed",
        "step_results": [{"result": "passed", "actual": "旧方案通过"}],
    }, format="json")
    assert recorded.status_code == 201, recorded.content
    row = recorded.data["current"]
    if submitted:
        row = workflow(session_client, base, defect, row, "submit").data["current"]
    session_client.force_authenticate(technician)
    edited = session_client.patch(base + f"solutions/{solution['id']}/", {
        "expected_version": solution["edit_version"], "steps": "新修复步骤",
    }, format="json")
    assert edited.status_code == 200, edited.content
    solution = approve(session_client, base, edited.data, manager)
    session_client.force_authenticate(tester)
    if submitted:
        session_client.force_authenticate(manager)
        rejected = workflow(session_client, base, defect, row, "accept")
        assert rejected.status_code == 409, rejected.content
    else:
        assert workflow(session_client, base, defect, row, "submit").status_code == 409
    data = session_client.get(base + f"defects/{defect.pk}/verification/").data
    assert not data["current"]["can_record"]
    assert not data["current"]["can_accept"]
    if submitted:
        returned = workflow(session_client, base, defect, row, "return_test", comment="新方案重新验证")
        assert returned.status_code == 200, returned.content
        assert returned.data["current"]["round_no"] == 2
        assert returned.data["current"]["summary"]["pending"] == 1
        return
    assert data["current"]["execution_state"] == "needs_arrangement"
    session_client.force_authenticate(technician)
    stale = configure(session_client, base, defect, assignee_id=str(tester.pk), solution_revision_id=old_revision)
    assert stale.status_code == 409, stale.content
    fresh = configure(session_client, base, defect, assignee_id=str(tester.pk), solution_revision_id=solution["current_revision_id"])
    assert fresh.status_code == 201, fresh.content
    assert fresh.data["current"]["round_no"] == 2
    assert fresh.data["current"]["summary"]["pending"] == 1
    assert fresh.data["history"][0]["summary"]["passed"] == 1


def test_generic_status_patch_cannot_close_without_tester_results_and_acceptance(session_client, repair_flow):
    base, _, defect, technician, tester, manager = repair_flow
    changed = session_client.patch(base + f"defects/{defect.pk}/", {
        "status": "resolved", "fixed_build": "v2",
    }, format="json")
    assert changed.status_code == 200, changed.content
    session_client.force_authenticate(manager)
    closed = session_client.patch(base + f"defects/{defect.pk}/", {
        "status": "closed", "verification_method": "manual", "verification_note": "企图跳过方案和测试",
    }, format="json")
    assert closed.status_code == 409, closed.content
    defect.refresh_from_db()
    assert defect.status == "resolved"
