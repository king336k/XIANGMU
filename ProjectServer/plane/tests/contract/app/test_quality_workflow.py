"""Managed functional testing migrates old45100 capability onto native plans."""

from uuid import uuid4

import pytest
from plane.db.models import Project, ProjectMember, User, WorkspaceMember

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def scenario(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="功能测试", identifier="FT")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    tester = User.objects.create(email="tester@quality.local", username="tester-unique", display_name="测试员")
    WorkspaceMember.objects.create(workspace=workspace, member=tester, role=15)
    ProjectMember.objects.create(project=project, member=tester, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    case = session_client.post(
        base + "cases/", {"title": "验收场景", "steps": [{"action": "执行功能", "expected": "成功"}]}, format="json"
    ).data
    response = session_client.post(
        base + "plans/",
        {"name": "功能验收", "build": "v2", "environment": "测试", "case_ids": [case["id"]], "managed": True},
        format="json",
    )
    assert response.status_code == 201
    return base, response.data, tester, create_user


def action(client, base, plan, verb, **data):
    return client.post(
        base + f"plans/{plan['id']}/workflow/",
        {"action": verb, "expected_version": plan["workflow_version"], **data},
        format="json",
    )


def run(client, base, item_id, result="passed"):
    return client.post(
        base + f"items/{item_id}/executions/",
        {"request_id": str(uuid4()), "result": result, "actual_result": "实测结果"},
        format="json",
    )


def test_assign_claim_execute_review_roundtrip(session_client, scenario):
    base, plan, tester, manager = scenario
    assert plan["managed"] and plan["status"] == "pending"
    assert run(session_client, base, plan["items"][0]["id"]).status_code == 409
    assigned = action(session_client, base, plan, "assign", assignee_id=str(tester.id))
    assert assigned.status_code == 200
    plan = assigned.data
    assert plan["status"] == "ready"
    session_client.force_authenticate(user=tester)
    plan = action(session_client, base, plan, "claim").data
    assert plan["status"] == "running"
    assert action(session_client, base, plan, "submit").status_code == 400
    assert run(session_client, base, plan["items"][0]["id"]).status_code == 201
    plan = action(session_client, base, plan, "submit").data
    assert plan["status"] == "review"
    assert action(session_client, base, plan, "approve").status_code == 403
    session_client.force_authenticate(user=manager)
    approved = action(session_client, base, plan, "approve", comment="验收通过")
    assert approved.status_code == 200 and approved.data["status"] == "completed"
    assert run(session_client, base, plan["items"][0]["id"]).status_code == 409
    assert len(approved.data["workflow_events"]) == 4


def test_return_requires_fresh_round_and_preserves_old_results(session_client, scenario):
    base, plan, tester, manager = scenario
    plan = action(session_client, base, plan, "assign", assignee_id=str(tester.id)).data
    session_client.force_authenticate(user=tester)
    plan = action(session_client, base, plan, "claim").data
    assert run(session_client, base, plan["items"][0]["id"]).status_code == 201
    plan = action(session_client, base, plan, "submit").data
    session_client.force_authenticate(user=manager)
    assert action(session_client, base, plan, "return").status_code == 400
    plan = action(session_client, base, plan, "return", comment="补充验证边界").data
    assert plan["round_no"] == 2 and plan["status"] == "returned"
    assert plan["summary"]["pending"] == 1
    session_client.force_authenticate(user=tester)
    plan = action(session_client, base, plan, "claim").data
    assert action(session_client, base, plan, "submit").status_code == 400
    assert run(session_client, base, plan["items"][0]["id"]).status_code == 201
    history = session_client.get(base + f"items/{plan['items'][0]['id']}/executions/").data
    assert {row["round_no"] for row in history["results"]} == {1, 2}


def test_workflow_assignment_permission_pause_and_stale_version(session_client, scenario):
    base, plan, tester, manager = scenario
    session_client.force_authenticate(user=tester)
    assert action(session_client, base, plan, "assign", assignee_id=str(tester.id)).status_code == 403
    session_client.force_authenticate(user=manager)
    changed = action(session_client, base, plan, "assign", assignee_id=str(tester.id)).data
    assert action(session_client, base, plan, "cancel", comment="旧页面").status_code == 409
    session_client.force_authenticate(user=tester)
    changed = action(session_client, base, changed, "claim").data
    changed = action(session_client, base, changed, "pause").data
    assert changed["status"] == "paused"
    assert run(session_client, base, changed["items"][0]["id"]).status_code == 409
    changed = action(session_client, base, changed, "resume").data
    assert changed["status"] == "running"


def test_failed_plan_can_submit_actual_results_but_cancelled_plan_cannot_approve(session_client, scenario):
    base, plan, tester, manager = scenario
    plan = action(session_client, base, plan, "assign", assignee_id=str(tester.id)).data
    session_client.force_authenticate(user=tester)
    plan = action(session_client, base, plan, "claim").data
    run(session_client, base, plan["items"][0]["id"], "failed")
    submitted = action(session_client, base, plan, "submit")
    assert submitted.status_code == 200
    plan = submitted.data
    session_client.force_authenticate(user=manager)
    assert action(session_client, base, plan, "approve").status_code == 400
    plan = action(session_client, base, plan, "cancel", comment="暂停发布").data
    assert plan["status"] == "cancelled"
    assert action(session_client, base, plan, "approve").status_code == 409


def test_guest_and_foreign_assignee_cannot_take_control(session_client, scenario, workspace):
    base, plan, tester, manager = scenario
    stranger = User.objects.create(email="stranger@workflow.local", username="stranger")
    response = action(session_client, base, plan, "assign", assignee_id=str(stranger.id))
    assert response.status_code == 400
    project = Project.objects.get(name="功能测试")
    ProjectMember.objects.filter(project=project, member=tester).update(role=5)
    session_client.force_authenticate(user=tester)
    assert action(session_client, base, plan, "claim").status_code == 403


def test_managed_creation_and_assignment_reject_readonly_assignees(session_client, scenario, workspace):
    from plane.db.models import ProjectMember, WorkspaceMember

    base, plan, tester, manager = scenario
    payload = {
        "name": "分派边界",
        "build": "v1",
        "environment": "本地",
        "managed": True,
        "assignee_id": str(tester.id),
        "case_ids": [plan["items"][0]["case_id"]],
    }
    ProjectMember.objects.filter(project_id=base.split("/")[5], member=tester).update(role=5)
    assert session_client.post(base + "plans/", payload, format="json").status_code == 400
    ProjectMember.objects.filter(member=tester).update(role=15)
    WorkspaceMember.objects.filter(workspace=workspace, member=tester).update(role=5)
    assert session_client.post(base + "plans/", payload, format="json").status_code == 400
    assert action(session_client, base, plan, "assign", assignee_id=str(tester.id)).status_code == 400


def test_failed_execution_can_be_reported_and_reviewed_but_does_not_admit_release(session_client, scenario):
    base, plan, tester, manager = scenario
    plan = action(session_client, base, plan, "assign", assignee_id=str(tester.id)).data
    session_client.force_authenticate(user=tester)
    plan = action(session_client, base, plan, "claim").data
    result = run(session_client, base, plan["items"][0]["id"], "failed")
    assert result.status_code == 201
    submitted = action(session_client, base, plan, "submit")
    assert submitted.status_code == 200, submitted.content
    session_client.force_authenticate(user=manager)
    accepted = action(session_client, base, submitted.data, "approve", comment="已确认本轮失败结果，安排修复")
    assert accepted.status_code == 200 and accepted.data["status"] == "completed"
    release = session_client.post(
        base + "releases/",
        {"name": "失败结果不可发布", "version": plan["build"], "plan_ids": [plan["id"]]},
        format="json",
    )
    assert release.status_code == 201, release.content
    admission = session_client.post(
        base + f"releases/{release.data['id']}/admit/", {"expected_version": 1}, format="json"
    )
    assert admission.status_code == 400, admission.content
    assert "通过" in str(admission.data)


@pytest.mark.parametrize(
    "matches,scope,expected", [(1, "functional", "open"), (2, "functional", "resolved"), (1, "data", "open")]
)
def test_failed_functional_regression_returns_only_unambiguous_current_fix(
    session_client, scenario, matches, scope, expected
):
    from django.utils import timezone
    from plane.quality.models import Defect

    base, plan, tester, manager = scenario
    defects = [
        Defect.objects.create(
            project_id=base.split("/")[5],
            created_by=manager,
            title=f"待验证功能{i}",
            case_id=plan["items"][0]["case_id"],
            status="resolved",
            fixed_build="v2",
            resolved_at=timezone.now(),
            verification_scope=scope,
        )
        for i in range(matches)
    ]
    plan = action(session_client, base, plan, "assign", assignee_id=str(tester.id)).data
    session_client.force_authenticate(user=tester)
    plan = action(session_client, base, plan, "claim").data
    assert run(session_client, base, plan["items"][0]["id"], "failed").status_code == 201
    submitted = action(session_client, base, plan, "submit")
    assert submitted.status_code == 200, submitted.content
    for defect in defects:
        defect.refresh_from_db()
        assert defect.status == expected
        if expected == "open":
            assert defect.resolved_at is None and defect.regression_execution_id is None
            assert defect.events.filter(previous_status="resolved", status="open", note__contains="回归失败").exists()
