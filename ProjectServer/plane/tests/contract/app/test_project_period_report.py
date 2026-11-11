"""Project period activity and current workload have distinct clocks and permission boundaries."""

from datetime import datetime, timezone as dt_timezone
import pytest
from plane.db.models import Project, ProjectMember, Issue, State, IssueAssignee
from plane.quality.models import Defect, DefectEvent, TestPlan, TestCase, CaseRevision, PlanItem, TestExecution

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def report_project(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="区间报表", identifier="PERIOD")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    return project, f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/project-report/"


def stamp(model, row, date, **extra):
    model.objects.filter(pk=row.pk).update(
        created_at=datetime.fromisoformat(date).replace(tzinfo=dt_timezone.utc), **extra
    )


def test_period_activity_does_not_confuse_current_state_or_reclose_events(session_client, report_project, create_user):
    project, url = report_project
    defect = Defect.objects.create(project=project, title="本期关闭后重开", assignee=create_user, status="open")
    stamp(Defect, defect, "2026-09-01T00:00:00")
    for day, previous, status in [
        ("2026-10-02T00:00:00", "resolved", "closed"),
        ("2026-10-03T00:00:00", "closed", "open"),
        ("2026-10-04T00:00:00", "resolved", "closed"),
        ("2026-10-05T00:00:00", "closed", "open"),
    ]:
        event = DefectEvent.objects.create(
            project=project, defect=defect, previous_status=previous, status=status, created_by=create_user
        )
        stamp(DefectEvent, event, day)
    future = Defect.objects.create(project=project, title="区间外", status="closed")
    stamp(Defect, future, "2026-11-01T00:00:00")
    fresh = Defect.objects.create(project=project, title="期末边界", status="in_progress")
    stamp(Defect, fresh, "2026-10-31T15:59:59.999999")
    response = session_client.get(url + "?timezone=UTC&start=2026-10-01&end=2026-10-31")
    assert response.status_code == 200, response.content
    data = response.data
    assert data["activity"]["defects_created"] == 1
    assert data["activity"]["defects_closed"] == 1  # unique defects, not closure event count
    assert data["current"]["defects_unclosed"] == 2
    assert data["activity"]["defects_reopened"] == 1
    assert len(data["trend"]) == 31
    assert data["workload"][0]["defects"]["open"] == 1
    assert data["unassigned"]["defects"]["in_progress"] == 1


def test_period_native_work_and_multiple_execution_results_count_as_recorded(
    session_client, report_project, create_user
):
    project, url = report_project
    state = State.objects.create(project=project, workspace=project.workspace, name="处理中", group="started")
    issue = Issue.objects.create(project=project, workspace=project.workspace, name="研发任务", state=state)
    stamp(Issue, issue, "2026-10-10T12:00:00")
    IssueAssignee.objects.create(project=project, workspace=project.workspace, issue=issue, assignee=create_user)
    case = TestCase.objects.create(project=project, title="步骤", steps=[])
    revision = CaseRevision.objects.create(project=project, case=case, version=1, title=case.title, snapshot={})
    plan = TestPlan.objects.create(
        project=project,
        name="测试任务",
        build="v1",
        environment="local",
        assignee=create_user,
        status="running",
        managed=True,
    )
    item = PlanItem.objects.create(project=project, plan=plan, case=case, revision=revision)
    import uuid

    for result in ["failed", "passed"]:
        execution = TestExecution.objects.create(
            project=project, item=item, request_id=uuid.uuid4(), result=result, created_by=create_user
        )
        stamp(TestExecution, execution, "2026-10-10T12:00:00")
    response = session_client.get(url + "?timezone=UTC&start=2026-10-10&end=2026-10-10")
    assert response.status_code == 200, response.content
    assert response.data["activity"]["work_created"] == 1
    assert response.data["activity"]["test_executions"] == 2
    assert response.data["activity"]["test_cases_executed"] == 1
    assert response.data["test_results"] == {"passed": 1, "failed": 1, "blocked": 0, "inconclusive": 0, "skipped": 0}
    row = response.data["workload"][0]
    assert row["work"]["started"] == 1 and row["plans"]["running"] == 1


@pytest.mark.parametrize(
    "query",
    [
        "start=x&end=2026-10-31",
        "start=2026-11-01&end=2026-10-01",
        "start=2020-01-01&end=2026-11-01",
        "start=2026-11-01",
    ],
)
def test_period_rejects_invalid_or_unbounded_dates(session_client, report_project, query):
    _, url = report_project
    assert session_client.get(url + "?" + query).status_code == 400


def test_period_rejects_hidden_project_and_guest(session_client, report_project, create_user, workspace):
    project, url = report_project
    ProjectMember.objects.filter(project=project, member=create_user).update(role=5)
    assert session_client.get(url + "?timezone=UTC&start=2026-10-01&end=2026-10-31").status_code == 403
    ProjectMember.objects.filter(project=project, member=create_user).delete()
    assert session_client.get(url + "?timezone=UTC&start=2026-10-01&end=2026-10-31").status_code == 403


def test_period_uses_shanghai_day_boundaries_and_drills_to_exact_records(session_client, report_project, create_user):
    project, url = report_project
    before = Defect.objects.create(project=project, title="开始前")
    included = Defect.objects.create(project=project, title="上海当天")
    after = Defect.objects.create(project=project, title="结束后")
    stamp(Defect, before, "2026-10-09T15:59:59")
    stamp(Defect, included, "2026-10-09T16:00:00")
    stamp(Defect, after, "2026-10-10T16:00:00")
    summary = session_client.get(url + "?start=2026-10-10&end=2026-10-10")
    assert summary.status_code == 200
    assert summary.data["activity"]["defects_created"] == 1
    detail = session_client.get(url + "?start=2026-10-10&end=2026-10-10&detail=defects_created")
    assert detail.status_code == 200 and detail.data["count"] == 1
    assert detail.data["results"][0]["id"] == str(included.id)


def test_personnel_current_workload_drilldown_is_exact_and_project_scoped(
    session_client, report_project, create_user, workspace
):
    project, url = report_project
    defect = Defect.objects.create(project=project, title="处理中", assignee=create_user, status="in_progress")
    other = Project.objects.create(workspace=workspace, name="其他", identifier="OTHER")
    Defect.objects.create(project=other, title="不能混入", assignee=create_user, status="in_progress")
    response = session_client.get(
        url
        + "?start=2026-10-01&end=2026-10-31&detail=workload&resource=defects&status=in_progress"
        + f"&assignee_id={create_user.id}"
    )
    assert response.status_code == 200, response.content
    assert response.data["count"] == 1 and response.data["results"][0]["id"] == str(defect.id)


def test_completed_native_history_survives_reopen_and_excludes_other_projects(
    session_client, report_project, create_user, workspace
):
    from plane.db.models import IssueActivity

    project, url = report_project
    active = State.objects.create(project=project, workspace=workspace, name="处理中", group="started")
    done = State.objects.create(project=project, workspace=workspace, name="已完成", group="completed")
    issue = Issue.objects.create(project=project, workspace=workspace, state=active, name="完成后重开")
    stamp(Issue, issue, "2026-09-01T00:00:00")
    event = IssueActivity.objects.create(
        project=project,
        workspace=workspace,
        issue=issue,
        field="state",
        new_identifier=done.id,
        old_identifier=active.id,
    )
    stamp(IssueActivity, event, "2026-10-10T00:00:00")
    response = session_client.get(url + "?start=2026-10-01&end=2026-10-31")
    assert response.status_code == 200
    assert response.data["activity"]["work_completed"] == 1
    assert response.data["current"]["work_unfinished"] == 1


def test_execution_result_drilldown_does_not_show_other_results(session_client, report_project, create_user):
    import uuid

    project, url = report_project
    case = TestCase.objects.create(project=project, title="回归", steps=[])
    revision = CaseRevision.objects.create(project=project, case=case, version=1, title=case.title, snapshot={})
    plan = TestPlan.objects.create(project=project, name="任务", build="v1", environment="local")
    item = PlanItem.objects.create(project=project, plan=plan, case=case, revision=revision)
    for result in ["passed", "failed"]:
        row = TestExecution.objects.create(project=project, item=item, request_id=uuid.uuid4(), result=result)
        stamp(TestExecution, row, "2026-10-10T00:00:00")
    response = session_client.get(url + "?start=2026-10-01&end=2026-10-31&detail=test_executions&result=failed")
    assert response.status_code == 200
    assert response.data["count"] == 1 and response.data["results"][0]["result"] == "failed"


def test_plain_fully_executed_plan_is_not_pending_and_current_drilldown_matches(session_client, report_project):
    import uuid

    project, url = report_project
    case = TestCase.objects.create(project=project, title="普通测试", steps=[])
    revision = CaseRevision.objects.create(project=project, case=case, version=1, title=case.title, snapshot={})
    plan = TestPlan.objects.create(project=project, name="已执行普通计划", build="v1", environment="local")
    item = PlanItem.objects.create(project=project, plan=plan, case=case, revision=revision)
    TestExecution.objects.create(project=project, item=item, request_id=uuid.uuid4(), result="passed")
    pending = TestPlan.objects.create(project=project, name="待执行普通计划", build="v2", environment="local")
    PlanItem.objects.create(project=project, plan=pending, case=case, revision=revision)
    query = "?start=2026-10-01&end=2026-10-31"
    response = session_client.get(url + query)
    assert response.status_code == 200, response.content
    assert response.data["current"]["plans_unfinished"] == 1
    detail = session_client.get(url + query + "&detail=current_plans")
    assert detail.status_code == 200 and detail.data["count"] == 1
    assert detail.data["results"][0]["id"] == str(pending.id)
