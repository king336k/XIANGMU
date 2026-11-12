"""Mature operations preserve frozen evidence and domain-specific verification gates."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import TestPlan

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def operations(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="操作闭环", identifier="OPS")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    case = session_client.post(
        base + "cases/", {"title": "原用例", "steps": [{"action": "操作", "expected": "预期"}]}, format="json"
    ).data
    plan = session_client.post(
        base + "plans/",
        {"name": "原计划", "build": "v1", "environment": "local", "case_ids": [case["id"]], "managed": True},
        format="json",
    ).data
    return base, project, case, plan


def test_unstarted_plan_can_edit_with_version_guard_but_running_content_is_frozen(session_client, operations):
    base, project, case, plan = operations
    url = base + f"plans/{plan['id']}/"
    changed = session_client.patch(url, {"name": "调整计划", "build": "v2", "expected_version": 1}, format="json")
    assert changed.status_code == 200, changed.content
    assert changed.data["build"] == "v2" and changed.data["workflow_version"] == 2
    assert session_client.patch(url, {"name": "旧页面覆盖", "expected_version": 1}, format="json").status_code == 409
    TestPlan.objects.filter(pk=plan["id"]).update(status="running")
    assert session_client.patch(url, {"build": "v3", "expected_version": 2}, format="json").status_code == 409
    assert TestPlan.objects.get(pk=plan["id"]).build == "v2"


def test_plan_copy_can_choose_original_frozen_or_latest_case_versions(session_client, operations):
    base, project, case, plan = operations
    assert (
        session_client.patch(
            base + f"cases/{case['id']}/", {"title": "新用例", "expected_version": 1}, format="json"
        ).status_code
        == 200
    )
    endpoint = base + f"plans/{plan['id']}/copy/"
    copied = session_client.post(
        endpoint,
        {"name": "按原版复测", "build": "v2", "environment": "staging", "use_latest": False, "expected_version": 1},
        format="json",
    )
    assert copied.status_code == 201, copied.content
    assert copied.data["status"] == "pending" and copied.data["assignee_id"] is None
    assert copied.data["items"][0]["revision"]["version"] == 1
    assert copied.data["summary"]["executed"] == 0
    latest = session_client.post(
        endpoint,
        {"name": "按最新版测试", "build": "v3", "environment": "staging", "use_latest": True, "expected_version": 1},
        format="json",
    )
    assert latest.status_code == 201 and latest.data["items"][0]["revision"]["version"] == 2, latest.content
    original = session_client.get(base + f"plans/{plan['id']}/").data
    assert original["items"][0]["revision"]["version"] == 1


def test_manual_defect_can_close_with_explicit_verification_without_forced_testcase(session_client, operations):
    base, project, case, plan = operations
    row = session_client.post(base + "defects/", {"title": "提示文案错误"}, format="json").data
    url = base + f"defects/{row['id']}/"
    assert (
        session_client.patch(
            url, {"status": "resolved", "fixed_build": "v2", "resolution": "修正页面提示"}, format="json"
        ).status_code
        == 200
    )
    assert (
        session_client.patch(url, {"status": "closed", "verification_method": "manual"}, format="json").status_code
        == 400
    )
    closed = session_client.patch(
        url,
        {
            "status": "closed",
            "verification_method": "manual",
            "verification_note": "已在v2打开页面，确认提示文案和展示位置符合要求",
        },
        format="json",
    )
    assert closed.status_code == 200 and closed.data["status"] == "closed", closed.content
    assert "人工验证" in closed.data["events"][0]["note"] and "v2" in closed.data["events"][0]["note"]
    assert closed.data["case_id"] is None


def test_test_generated_defect_cannot_use_manual_verification_to_skip_case_regression(session_client, operations):
    base, project, case, plan = operations
    row = session_client.post(base + "defects/", {"title": "需用例验证", "case_id": case["id"]}, format="json").data
    url = base + f"defects/{row['id']}/"
    assert session_client.patch(url, {"status": "resolved", "fixed_build": "v2"}, format="json").status_code == 200
    response = session_client.patch(
        url,
        {"status": "closed", "verification_method": "manual", "verification_note": "试图跳过已有回归用例"},
        format="json",
    )
    assert response.status_code == 400


def test_daq_origin_does_not_require_retired_external_regression(session_client, operations, create_user):
    base, project, case, plan = operations
    row = session_client.post(base + "defects/", {"title": "正常功能联调"}, format="json").data
    url = base + f"defects/{row['id']}/"
    assert session_client.patch(url, {"status": "resolved", "fixed_build": "v2"}, format="json").status_code == 200
    response = session_client.patch(
        url,
        {"status": "closed", "verification_method": "manual", "verification_note": "已在修复版本现场验证功能通过"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.data["status"] == "closed" and not response.data["requires_data_regression"]


def test_nonmanager_cannot_manually_close_defect(session_client, operations, create_user):
    base, project, case, plan = operations
    row = session_client.post(base + "defects/", {"title": "人工验证职责"}, format="json").data
    url = base + f"defects/{row['id']}/"
    assert session_client.patch(url, {"status": "resolved", "fixed_build": "v2"}, format="json").status_code == 200
    ProjectMember.objects.filter(project=project, member=create_user).update(role=15)
    response = session_client.patch(
        url, {"status": "closed", "verification_method": "manual", "verification_note": "成员越权关闭"}, format="json"
    )
    assert response.status_code == 403


def test_plan_copy_lists_latest_versions_and_allows_case_selection(session_client, operations):
    base, project, case, plan = operations
    added = session_client.post(
        base + "cases/", {"title": "新增回归", "steps": [{"action": "打开", "expected": "正常"}]}, format="json"
    ).data
    session_client.patch(base + f"cases/{case['id']}/", {"title": "更新步骤说明", "expected_version": 1}, format="json")
    original = session_client.get(base + f"plans/{plan['id']}/")
    assert original.status_code == 200
    assert original.data["items"][0]["current_case_version"] == 2
    assert original.data["items"][0]["revision"]["version"] == 1
    copy = session_client.post(
        base + f"plans/{plan['id']}/copy/",
        {"name": "选择用例复测", "expected_version": 1, "use_latest": False, "case_ids": [added["id"]]},
        format="json",
    )
    assert copy.status_code == 201, copy.content
    assert [str(item["case_id"]) for item in copy.data["items"]] == [added["id"]]
    assert str(session_client.get(base + f"plans/{plan['id']}/").data["items"][0]["case_id"]) == case["id"]


def test_preexecution_plan_can_adjust_case_list_but_history_cannot(session_client, operations):
    base, project, case, plan = operations
    added = session_client.post(
        base + "cases/", {"title": "新增用例", "steps": [{"action": "打开", "expected": "正常"}]}, format="json"
    ).data
    result = session_client.patch(
        base + f"plans/{plan['id']}/", {"expected_version": 1, "case_ids": [case["id"], added["id"]]}, format="json"
    )
    assert result.status_code == 200, result.content
    assert len(result.data["items"]) == 2
    TestPlan.objects.filter(pk=plan["id"]).update(status="running")
    assert (
        session_client.patch(
            base + f"plans/{plan['id']}/", {"expected_version": 2, "case_ids": [added["id"]]}, format="json"
        ).status_code
        == 409
    )
