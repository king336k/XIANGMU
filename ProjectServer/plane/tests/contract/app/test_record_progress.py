"""Read-only per-record progress reuses historical facts and project boundaries."""

import pytest
from plane.db.models import Project, ProjectMember
from plane.quality.models import Defect, DefectEvent, TestPlan, PlanEvent, ProjectVersion

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def progress_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="记录历程", identifier="PROGRESS")
    ProjectMember.objects.create(project=project, workspace=workspace, member=create_user, role=20)
    return project, f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/record-progress/"


def test_defect_history_and_version_milestones_are_real_and_scoped(session_client, progress_project, create_user):
    project, url = progress_project
    defect = Defect.objects.create(project=project, title="修复记录", status="resolved", affected_build="v2")
    DefectEvent.objects.create(
        project=project,
        created_by=create_user,
        defect=defect,
        previous_status="in_progress",
        status="resolved",
        note="已修复并提交回归",
    )
    version = ProjectVersion.objects.create(
        project=project,
        name="第二版",
        version="v2",
        flow_nodes=[{"id": "release", "name": "发布验收", "kind": "milestone", "depends_on": [], "join": "all"}],
    )
    result = session_client.get(url + f"?kind=defect&id={defect.id}")
    assert result.status_code == 200, result.content
    assert result.data["current"] == "resolved"
    assert result.data["events"][0]["note"] == "已修复并提交回归"
    assert result.data["versions"][0]["id"] == str(version.id)
    assert result.data["versions"][0]["milestones"][0]["name"] == "发布验收"
    assert not version.flow_state  # read-only projection does not advance workflow


def test_managed_plan_history_uses_actual_status_not_test_pass_assumption(
    session_client, progress_project, create_user
):
    project, url = progress_project
    plan = TestPlan.objects.create(
        project=project, name="经理确认结果", build="v1", environment="local", managed=True, status="review"
    )
    PlanEvent.objects.create(
        project=project,
        created_by=create_user,
        plan=plan,
        action="submit",
        previous_status="running",
        status="review",
        round_no=1,
        note="等待确认",
    )
    result = session_client.get(url + f"?kind=plan&id={plan.id}")
    assert result.status_code == 200
    assert result.data["current"] == "review" and result.data["events"][0]["label"] == "待确认"


def test_record_progress_does_not_read_cross_project_record(session_client, progress_project, workspace):
    project, url = progress_project
    other = Project.objects.create(workspace=workspace, name="不可见", identifier="PIO")
    defect = Defect.objects.create(project=other, title="不可泄漏")
    assert session_client.get(url + f"?kind=defect&id={defect.id}").status_code == 404


def test_requirement_timeline_reuses_own_and_child_task_dates(session_client, progress_project, workspace):
    from plane.db.models import Issue
    from plane.quality.models import Requirement
    from datetime import date

    project, url = progress_project
    issue = Issue.objects.create(
        project=project,
        workspace=workspace,
        name="需求排期",
        start_date=date(2026, 11, 1),
        target_date=date(2026, 11, 10),
    )
    Requirement.objects.create(project=project, issue=issue)
    child = Issue.objects.create(
        project=project,
        workspace=workspace,
        name="关联开发任务",
        parent=issue,
        start_date=date(2026, 11, 2),
        target_date=date(2026, 11, 8),
    )
    result = session_client.get(url + f"?kind=requirement&id={issue.id}")
    assert result.status_code == 200, result.content
    schedules = {row["name"]: row for row in result.data["schedule"]}
    assert schedules["关联开发任务"]["start"] == date(2026, 11, 2)
    assert len(schedules) == 2 and str(child.id) in schedules["关联开发任务"]["path"]


@pytest.mark.parametrize(
    "status,label",
    [
        ("failed", "回归失败，待修复"),
        ("paused", "已暂停"),
        ("returned", "待复测"),
        ("cancelled", "已取消"),
    ],
)
def test_plan_history_translates_terminal_and_previous_states(
    session_client, progress_project, create_user, status, label
):
    project, url = progress_project
    plan = TestPlan.objects.create(
        project=project, name="状态历程", build="v1", environment="local", managed=True, status="completed"
    )
    PlanEvent.objects.create(
        project=project,
        created_by=create_user,
        plan=plan,
        action="submit",
        previous_status="running",
        status=status,
        round_no=1,
    )
    result = session_client.get(url + f"?kind=plan&id={plan.id}")
    assert result.status_code == 200
    assert result.data["events"][0]["label"] == label


@pytest.mark.parametrize("kind", ["defect", "requirement", "plan", "managed_plan"])
def test_record_history_after_200_is_reachable_with_count_and_stable_current(
    session_client, progress_project, create_user, kind
):
    from plane.db.models import Issue
    from plane.quality.models import Requirement, RequirementRevision, TestCase, CaseRevision, PlanItem, TestExecution
    from uuid import uuid4

    project, url = progress_project
    query_kind = "plan" if kind == "managed_plan" else kind
    if kind == "defect":
        row = Defect.objects.create(project=project, title="201条缺陷历史", status="resolved")
        rows = [
            DefectEvent(project=project, created_by=create_user, defect=row, status="open", note=f"event-{i}")
            for i in range(201)
        ]
        DefectEvent.objects.bulk_create(rows)
        pk = row.id
    elif kind == "requirement":
        issue = Issue.objects.create(project=project, workspace=project.workspace, name="201版本需求")
        row = Requirement.objects.create(project=project, issue=issue, status="approved")
        rows = [
            RequirementRevision(
                project=project,
                created_by=create_user,
                requirement=row,
                version=i + 1,
                snapshot={"status": "draft", "comment": f"event-{i}"},
            )
            for i in range(201)
        ]
        RequirementRevision.objects.bulk_create(rows)
        pk = issue.id
    else:
        row = TestPlan.objects.create(
            project=project,
            name="201次执行",
            build="v2",
            environment="local",
            managed=kind == "managed_plan",
            status="review",
        )
        if kind == "managed_plan":
            rows = [
                PlanEvent(
                    project=project,
                    created_by=create_user,
                    plan=row,
                    action="submit",
                    previous_status="running",
                    status="running",
                    round_no=1,
                    note=f"event-{i}",
                )
                for i in range(201)
            ]
            PlanEvent.objects.bulk_create(rows)
        else:
            case = TestCase.objects.create(project=project, title="普通执行")
            revision = CaseRevision.objects.create(project=project, case=case, version=1, title=case.title, snapshot={})
            item = PlanItem.objects.create(project=project, plan=row, case=case, revision=revision)
            rows = [
                TestExecution(project=project, created_by=create_user, item=item, result="passed", request_id=uuid4())
                for i in range(201)
            ]
            TestExecution.objects.bulk_create(rows)
            PlanEvent.objects.create(
                project=project,
                plan=row,
                created_by=create_user,
                action="create",
                previous_status="",
                status="pending",
                round_no=1,
                note="latest workflow event",
            )
        pk = row.id
    path = url + f"?kind={query_kind}&id={pk}"
    first = session_client.get(path + "&page=1&per_page=100")
    last = session_client.get(path + "&page=3&per_page=100")
    assert first.status_code == last.status_code == 200
    assert first.data["event_pagination"]["count"] == (202 if kind == "plan" else 201)
    assert len(first.data["events"]) == 100
    assert len(last.data["events"]) == (2 if kind == "plan" else 1)
    assert not {event["id"] for event in first.data["events"]} & {event["id"] for event in last.data["events"]}
    assert str(rows[-1].id) in {event["id"] for event in last.data["events"]}
    assert (
        first.data["current"]
        == last.data["current"]
        == ("completed" if kind == "plan" else "review" if kind == "managed_plan" else row.status)
    )


@pytest.mark.parametrize("size", [20, 50, 100])
def test_history_page_sizes_project_scope_and_private_signature_note(
    session_client, progress_project, create_user, workspace, size
):
    import json

    project, url = progress_project
    defect = Defect.objects.create(project=project, title="分页安全")
    DefectEvent.objects.bulk_create(
        [
            DefectEvent(
                project=project,
                created_by=create_user,
                defect=defect,
                status="open",
                note=json.dumps({"message": "可见说明", "incidentSignature": "synthetic-no-authority"}),
            )
            for i in range(101)
        ]
    )
    path = url + f"?kind=defect&id={defect.id}"
    response = session_client.get(path + f"&page=2&per_page={size}")
    assert response.status_code == 200
    assert response.data["event_pagination"]["count"] == 101
    assert response.data["event_pagination"]["page"] == 2
    assert response.data["event_pagination"]["per_page"] == size
    assert len(response.data["events"]) == min(size, 101 - size)
    assert all(event["note"] == "可见说明" for event in response.data["events"])
    other = Project.objects.create(workspace=workspace, name="外部记录", identifier="OTHERH")
    hidden = Defect.objects.create(project=other, title="不可跨项目翻页")
    assert session_client.get(url + f"?kind=defect&id={hidden.id}&page=2").status_code == 404
    assert session_client.get(path + "&page=999").status_code == 404
