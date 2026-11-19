"""Progress display follows actual transitions, including skipped and reopened work."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, DefectEvent

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def progress_display(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="进度展示", identifier="PRDISPLAY")
    ProjectMember.objects.create(project=project, workspace=workspace, member=create_user, role=20)
    row = Defect.objects.create(project=project, created_by=create_user, title="真实阶段", status="resolved")
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/record-progress/?kind=defect&id={row.id}"
    return project, row, url, create_user


def test_skipped_stages_are_not_marked_complete_and_state_ignores_history_pagination(session_client, progress_display):
    project, row, url, actor = progress_display
    DefectEvent.objects.create(
        project=project, defect=row, created_by=actor, previous_status="", status="open", note="手工提交缺陷"
    )
    DefectEvent.objects.create(
        project=project, defect=row, created_by=actor, previous_status="open", status="resolved", note="已修复"
    )
    response = session_client.get(url)
    assert response.status_code == 200, response.content
    state = {stage["key"]: stage["state"] for stage in response.data["stages"]}
    assert state == {"open": "completed", "in_progress": "skipped", "needs_tech": "skipped", "pending_tech": "skipped", "resolved": "current", "closed": "pending"}
    # Completion facts must not change when the visible history page changes.
    for _ in range(24):
        DefectEvent.objects.create(
            project=project,
            defect=row,
            created_by=actor,
            previous_status="resolved",
            status="resolved",
            note="补充证据",
        )
    page2 = session_client.get(url + "&page=2&per_page=20")
    assert page2.status_code == 200
    assert {stage["key"]: stage["state"] for stage in page2.data["stages"]} == state


def test_reopen_clears_previous_round_completion_and_keeps_specific_actions(session_client, progress_display):
    project, row, url, actor = progress_display
    actor.__class__.objects.filter(pk=actor.pk).update(display_name="", username="progress-actor")
    actor.username = "progress-actor"
    for before, after, note in [
        ("", "open", "手工提交缺陷"),
        ("open", "in_progress", "认领"),
        ("in_progress", "resolved", "提交修复"),
        ("resolved", "closed", "验收通过"),
        ("closed", "open", "重开，发现遗漏"),
        ("open", "open", "验证安排：补测登录"),
    ]:
        DefectEvent.objects.create(
            project=project, defect=row, created_by=actor, previous_status=before, status=after, note=note
        )
    row.status = "open"
    row.save(update_fields=["status"])
    response = session_client.get(url)
    assert response.status_code == 200
    state = {stage["key"]: stage["state"] for stage in response.data["stages"]}
    assert state == {"open": "current", "in_progress": "pending", "needs_tech": "pending", "pending_tech": "pending", "resolved": "pending", "closed": "pending"}
    assert response.data["events"][-2]["label"] == "已关闭 → 待处理"
    assert response.data["events"][-2]["tone"] == "failed"
    assert response.data["events"][-1]["label"] == "验证安排"
    assert response.data["events"][-1]["actor"] == actor.username


def test_completed_stage_is_actual_departure_and_cancel_is_not_completion():
    from plane.quality.record_progress import stage_states

    stages = [
        ("pending", "待分派"),
        ("running", "测试中"),
        ("review", "待确认"),
        ("completed", "已完成"),
        ("cancelled", "已取消"),
    ]
    state = stage_states(stages, "review", [("pending", "running"), ("running", "review")])
    assert state["pending"] == state["running"] == "completed"
    assert state["review"] == "current" and state["completed"] == "pending"
    cancelled = stage_states(stages, "cancelled", [("pending", "cancelled")])
    assert cancelled["pending"] == "pending" and cancelled["cancelled"] == "current"


def test_closed_forward_jump_marks_skipped_and_backward_reopens_work():
    from plane.quality.record_progress import stage_states

    stages = [("open", "待处理"), ("in_progress", "处理中"), ("resolved", "待回归"), ("closed", "已关闭")]
    history = [("", "open"), ("open", "resolved"), ("resolved", "closed")]
    assert stage_states(stages, "closed", history) == {
        "open": "completed",
        "in_progress": "skipped",
        "resolved": "completed",
        "closed": "current",
    }
    assert stage_states(stages, "in_progress", history + [("closed", "in_progress")]) == {
        "open": "completed",
        "in_progress": "current",
        "resolved": "pending",
        "closed": "pending",
    }
    assert stage_states(stages, "open", history + [("closed", "open")]) == {
        "open": "current",
        "in_progress": "pending",
        "resolved": "pending",
        "closed": "pending",
    }


def test_remote_progress_keeps_summary_details_and_reuses_serializer_projection_cache(session_client, progress_display):
    from unittest.mock import patch
    project, row, url, actor = progress_display
    events = [DefectEvent.objects.create(project=project, defect=row, created_by=actor,
        previous_status="resolved", status="resolved", note=f"Agent 检查：任务 {row.id}；事件{index}") for index in range(2)]
    contexts = []
    process = {"summary": "BASEKNOW-D-477 第1轮检查配置完成", "stage": "inspect", "defect_code": "BASEKNOW-D-477", "command": {"path": "/home/robot/config.json", "exit_code": 0}, "run_id": str(row.id)}
    def project_event(event, context):
        contexts.append(context)
        context.setdefault("shared-lookup", process)
        return context["shared-lookup"]
    with patch("plane.quality.remote_event_display.event_process", side_effect=project_event):
        response = session_client.get(url)
    assert response.status_code == 200, response.content
    projected = [item for item in response.data["events"] if item["id"] in {str(event.id) for event in events}]
    assert len(projected) == 2
    for item, event in zip(projected, events):
        assert item["note"] == process["summary"]
        assert event.note in item["details"]
        assert item["remote_process"] == process
    assert len(contexts) == 2 and contexts[0] is contexts[1]
