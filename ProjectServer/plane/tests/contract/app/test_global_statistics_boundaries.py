"""Read-only review counterexamples; product code is never edited by this script."""

from datetime import datetime, timezone as dt_timezone
from uuid import uuid4
import pytest
from plane.db.models import (
    Project,
    ProjectMember,
    WorkspaceMember,
    User,
    Issue,
    IssueAssignee,
    State,
)
from plane.quality.models import (
    TestPlan as QualityPlan,
    TestCase as QualityCase,
    CaseRevision,
    PlanItem,
    TestExecution as QualityExecution,
    Requirement,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def stats_case(workspace, create_user):
    project = Project.objects.create(
        workspace=workspace, name="全局统计反例", identifier="GST152"
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    return project, base


def period(client, base, **params):
    response = client.get(
        base + "project-report/", {"start": "2026-10-01", "end": "2026-10-31", **params}
    )
    assert response.status_code == 200, response.content
    return response.data


def plan_item(project, **params):
    case = QualityCase.objects.create(project=project, title="用例", steps=[])
    revision = CaseRevision.objects.create(
        project=project, case=case, version=1, title=case.title, snapshot={}
    )
    plan = QualityPlan.objects.create(
        project=project, name="计划", build="v", environment="local", **params
    )
    item = PlanItem.objects.create(
        project=project, plan=plan, case=case, revision=revision
    )
    return plan, item


def test_failed_managed_plan_is_not_current_workload(
    session_client, stats_case, create_user
):
    project, base = stats_case
    plan_item(project, managed=True, status="failed", assignee=create_user)
    data = period(session_client, base)
    assert data["current"]["plans_unfinished"] == 0, data["current"]
    assert period(session_client, base, detail="current_plans")["count"] == 0


def test_ordinary_plan_uses_same_any_round_completion_as_summary(
    session_client, stats_case, create_user
):
    project, base = stats_case
    plan, item = plan_item(project, managed=False, round_no=2, assignee=create_user)
    QualityExecution.objects.create(
        project=project, item=item, round_no=1, request_id=uuid4(), result="passed"
    )
    summary = session_client.get(base + f"plans/{plan.id}/").data["summary"]
    assert summary["pending"] == 0, summary
    data = period(session_client, base)
    assert data["current"]["plans_unfinished"] == 0, {
        "detail_summary": summary,
        "period": data["current"],
    }


@pytest.mark.parametrize("business_status", ["completed", "cancelled", "archived"])
def test_terminal_requirement_not_current_workload_without_issue_state_change(
    session_client, stats_case, create_user, workspace, business_status
):
    project, base = stats_case
    state = State.objects.create(
        project=project, workspace=workspace, name="需求实现中", group="started"
    )
    issue = Issue.objects.create(
        project=project, workspace=workspace, name="取消的需求", state=state
    )
    IssueAssignee.objects.create(
        project=project, workspace=workspace, issue=issue, assignee=create_user
    )
    Requirement.objects.create(project=project, issue=issue, status=business_status)
    data = period(session_client, base)
    assert data["current"]["work_unfinished"] == 0, data["current"]
    assert period(session_client, base, detail="current_work")["count"] == 0


def test_inactive_account_is_not_active_personnel_in_period_or_native_stats(
    session_client, stats_case, workspace
):
    project, base = stats_case
    other = User.objects.create(
        username="globalstats-disabled",
        email="globalstats-disabled@example.invalid",
        is_active=False,
    )
    WorkspaceMember.objects.create(
        workspace=workspace, member=other, role=15, is_active=True
    )
    ProjectMember.objects.create(project=project, member=other, role=15, is_active=True)
    data = period(session_client, base)
    assert str(other.id) not in {r["user_id"] for r in data["workload"]}, data[
        "workload"
    ]
    native = session_client.get(
        f"/api/workspaces/{workspace.slug}/project-stats/",
        {"project_ids": str(project.id), "fields": "total_members"},
    )
    assert native.status_code == 200, native.content
    assert native.data[0]["total_members"] == 1, native.data


def test_native_yesterday_respects_shanghai_day(
    session_client, stats_case, workspace, mocker
):
    project, _ = stats_case
    state = State.objects.create(
        project=project, workspace=workspace, name="开发", group="started"
    )
    issue = Issue.objects.create(
        project=project, workspace=workspace, name="北京时间昨天23点", state=state
    )
    Issue.objects.filter(pk=issue.pk).update(
        created_at=datetime(2026, 10, 9, 15, 30, tzinfo=dt_timezone.utc)
    )
    # At UTC Oct9 17:00 it is Shanghai Oct10 01:00. "Yesterday" is Shanghai Oct9.
    mocker.patch(
        "plane.utils.date_utils.timezone.now",
        return_value=datetime(2026, 10, 9, 17, 0, tzinfo=dt_timezone.utc),
    )
    response = session_client.get(
        f"/api/workspaces/{workspace.slug}/advance-analytics/",
        {
            "tab": "work-items",
            "project_ids": str(project.id),
            "date_filter": "yesterday",
        },
    )
    assert response.status_code == 200, response.content
    assert response.data["total_work_items"]["count"] == 1, response.data


def test_native_member_counter_excludes_inactive_account_and_workspace_membership(
    session_client, stats_case, workspace
):
    project, _ = stats_case
    disabled = User.objects.create(
        username="stats-native-disabled",
        email="stats-native-disabled@example.invalid",
        is_active=False,
    )
    removed = User.objects.create(
        username="stats-native-removed", email="stats-native-removed@example.invalid"
    )
    for user, active in [(disabled, True), (removed, False)]:
        WorkspaceMember.objects.create(
            workspace=workspace, member=user, role=15, is_active=active
        )
        ProjectMember.objects.create(
            project=project, member=user, role=15, is_active=True
        )
    response = session_client.get(
        f"/api/workspaces/{workspace.slug}/project-stats/",
        {"project_ids": str(project.id), "fields": "total_members"},
    )
    assert response.status_code == 200, response.content
    assert response.data[0]["total_members"] == 1, response.data


def test_managed_current_round_summary_remains_independent_of_ordinary_semantics(
    session_client, stats_case
):
    project, base = stats_case
    plan, item = plan_item(project, managed=True, status="returned", round_no=2)
    QualityExecution.objects.create(
        project=project, item=item, round_no=1, request_id=uuid4(), result="passed"
    )
    response = session_client.get(base + f"plans/{plan.id}/")
    assert (
        response.status_code == 200 and response.data["summary"]["pending"] == 1
    ), response.content
    assert period(session_client, base)["current"]["plans_unfinished"] == 1


def test_terminal_requirement_stays_in_created_activity_history(
    session_client, stats_case, create_user, workspace
):
    project, base = stats_case
    state = State.objects.create(
        project=project, workspace=workspace, name="历史需求开发", group="started"
    )
    issue = Issue.objects.create(
        project=project, workspace=workspace, name="已取消的历史创建", state=state
    )
    Issue.objects.filter(pk=issue.pk).update(
        created_at=datetime(2026, 10, 10, 4, tzinfo=dt_timezone.utc)
    )
    Requirement.objects.create(project=project, issue=issue, status="cancelled")
    data = period(session_client, base)
    assert data["activity"]["work_created"] == 1
    assert period(session_client, base, detail="work_created")["count"] == 1


def test_disabled_owner_load_is_historical_and_drilldown_agrees(
    session_client, stats_case, workspace
):
    from plane.quality.models import Defect

    project, base = stats_case
    other = User.objects.create(
        username="stats-disabled-owner",
        email="stats-disabled-owner@example.invalid",
        is_active=False,
    )
    WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
    ProjectMember.objects.create(project=project, member=other, role=15)
    Defect.objects.create(
        project=project,
        title="原停用负责人待交接",
        assignee=other,
        status="in_progress",
    )
    data = period(session_client, base)
    previous = next(row for row in data["workload"] if row["user_id"] == "outside")
    assert previous["defects"] == {"in_progress": 1}
    assert (
        period(
            session_client,
            base,
            detail="workload",
            resource="defects",
            status="in_progress",
            assignee_id="outside",
        )["count"]
        == 1
    )


@pytest.mark.parametrize(
    "period_name,days",
    [("last_7_days", 7), ("last_30_days", 30), ("last_3_months", 90)],
)
def test_native_recent_periods_have_matching_n_day_current_previous_and_chart(
    period_name, days, mocker
):
    from plane.utils.date_utils import get_analytics_date_range, get_chart_period_range
    from zoneinfo import ZoneInfo

    mocker.patch(
        "plane.utils.date_utils.timezone.now",
        return_value=datetime(2026, 10, 9, 17, 0, tzinfo=dt_timezone.utc),
    )
    ranges = get_analytics_date_range(period_name)
    current = ranges["current"]
    previous = ranges["previous"]
    chart = get_chart_period_range(period_name)
    assert (current["lte"].date() - current["gte"].date()).days + 1 == days
    assert (previous["lte"].date() - previous["gte"].date()).days + 1 == days
    assert current["gte"].tzinfo == ZoneInfo("Asia/Shanghai") and current[
        "lte"
    ].tzinfo == ZoneInfo("Asia/Shanghai")
    assert chart == (current["gte"].date(), current["lte"].date())
    assert current["gte"].date().toordinal() == previous["lte"].date().toordinal() + 1


def test_native_chart_yesterday_uses_china_even_with_utc_user_timezone(
    session_client, stats_case, workspace, mocker, create_user
):
    project, _ = stats_case
    create_user.user_timezone = "UTC"
    create_user.save(update_fields=["user_timezone"])
    state = State.objects.create(
        project=project, workspace=workspace, name="图表统计", group="started"
    )
    issue = Issue.objects.create(
        project=project, workspace=workspace, name="北京时间昨天凌晨", state=state
    )
    Issue.objects.filter(pk=issue.pk).update(
        created_at=datetime(2026, 10, 8, 17, 0, tzinfo=dt_timezone.utc)
    )
    mocker.patch(
        "plane.utils.date_utils.timezone.now",
        return_value=datetime(2026, 10, 10, 4, 0, tzinfo=dt_timezone.utc),
    )
    response = session_client.get(
        f"/api/workspaces/{workspace.slug}/advance-analytics-charts/",
        {
            "type": "projects",
            "project_ids": str(project.id),
            "date_filter": "yesterday",
        },
        HTTP_X_TIMEZONE="UTC",
    )
    assert response.status_code == 200, response.content
    assert (
        next(row["count"] for row in response.data if row["key"] == "work_items") == 1
    ), response.data


def test_outside_bucket_counts_each_work_item_once_and_matches_drilldown(
    session_client, stats_case, workspace
):
    project, base = stats_case
    state = State.objects.create(
        project=project, workspace=workspace, name="待交接的任务", group="started"
    )
    issue = Issue.objects.create(
        project=project, workspace=workspace, name="两个离开负责人同一任务", state=state
    )
    for index in range(2):
        user = User.objects.create(
            username=f"stats-outside-{index}",
            email=f"stats-outside-{index}@example.invalid",
        )
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(
            project=project, member=user, role=15, is_active=False
        )
        IssueAssignee.objects.create(
            project=project, workspace=workspace, issue=issue, assignee=user
        )
    data = period(session_client, base)
    outside = next(row for row in data["workload"] if row["user_id"] == "outside")
    detail = period(
        session_client,
        base,
        detail="workload",
        resource="work",
        status="started",
        assignee_id="outside",
    )
    assert outside["work"]["started"] == detail["count"] == 1, {
        "outside": outside,
        "detail": detail,
    }


@pytest.mark.parametrize("project_scoped", [False, True])
def test_native_stats_grouping_applies_same_selected_china_window(
    session_client, stats_case, workspace, mocker, project_scoped
):
    project, _ = stats_case
    state = State.objects.create(
        project=project, workspace=workspace, name="开发日期分组", group="started"
    )
    for title, day in [("昨天", 9), ("区间外", 1)]:
        issue = Issue.objects.create(
            project=project, workspace=workspace, name=title, state=state
        )
        Issue.objects.filter(pk=issue.pk).update(
            created_at=datetime(2026, 10, day, 4, tzinfo=dt_timezone.utc)
        )
    mocker.patch(
        "plane.utils.date_utils.timezone.now",
        return_value=datetime(2026, 10, 10, 4, tzinfo=dt_timezone.utc),
    )
    scope = f"projects/{project.id}/" if project_scoped else ""
    response = session_client.get(
        f"/api/workspaces/{workspace.slug}/{scope}advance-analytics-stats/",
        {
            "project_ids": str(project.id),
            "type": "work-items",
            "date_filter": "yesterday",
        },
    )
    assert response.status_code == 200, response.content
    assert sum(row["started_work_items"] for row in response.data) == 1, response.data


def test_native_custom_created_at_day_bucket_is_china_for_utc_user(session_client,stats_case,workspace,create_user,mocker):
    project,_=stats_case
    create_user.user_timezone="UTC";create_user.save(update_fields=["user_timezone"])
    state=State.objects.create(project=project,workspace=workspace,name="开发",group="started")
    issue=Issue.objects.create(project=project,workspace=workspace,name="北京时间昨日零点后",state=state)
    Issue.objects.filter(pk=issue.pk).update(created_at=datetime(2026,10,9,16,30,tzinfo=dt_timezone.utc))
    mocker.patch("plane.utils.date_utils.timezone.now",return_value=datetime(2026,10,10,17,0,tzinfo=dt_timezone.utc))
    response=session_client.get(f"/api/workspaces/{workspace.slug}/advance-analytics-charts/",{"type":"custom-work-items","project_ids":str(project.id),"date_filter":"yesterday","x_axis":"CREATED_AT"})
    assert response.status_code==200,response.content
    rows=response.data["data"]
    assert len(rows)==1 and str(rows[0]["key"])=="2026-10-10",response.data
