"""Project-scoped cycle/module charts count current linked issues by their China creation day."""

from datetime import date, datetime, timezone as dt_timezone
import pytest
from plane.db.models import (
    Cycle,
    CycleIssue,
    Issue,
    Module,
    ModuleIssue,
    Project,
    ProjectMember,
    State,
)

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def chart_scope(workspace, create_user):
    project = Project.objects.create(
        workspace=workspace, name="周期模块统计", identifier="CM152"
    )
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    create_user.user_timezone = "UTC"
    create_user.save(update_fields=["user_timezone"])
    url = f"/api/workspaces/{workspace.slug}/projects/{project.id}/advance-analytics-charts/"
    return project, url


def container(project, actor, kind, incomplete=False):
    if kind == "cycle":
        return Cycle.objects.create(
            project=project,
            workspace=project.workspace,
            name="测试周期",
            owned_by=actor,
            start_date=datetime(2026, 10, 9, 16, tzinfo=dt_timezone.utc),
            end_date=(
                None
                if incomplete
                else datetime(2026, 10, 11, 15, 59, tzinfo=dt_timezone.utc)
            ),
        )
    return Module.objects.create(
        project=project,
        workspace=project.workspace,
        name="测试模块",
        start_date=date(2026, 10, 10),
        target_date=None if incomplete else date(2026, 10, 11),
    )


@pytest.mark.parametrize("kind", ["cycle", "module"])
def test_unscheduled_end_returns_empty_chart_not_server_error(
    session_client, chart_scope, create_user, kind
):
    project, url = chart_scope
    item = container(project, create_user, kind, incomplete=True)
    session_client.raise_request_exception = False
    response = session_client.get(
        url, {"type": "work-items", kind + "_id": str(item.id)}
    )
    assert response.status_code == 200, response.content[:200]
    assert response.data["data"] == []


@pytest.mark.parametrize("kind", ["cycle", "module"])
@pytest.mark.parametrize(
    "endpoint",
    ["advance-analytics-charts", "advance-analytics", "advance-analytics-stats"],
)
def test_foreign_project_dates_cannot_be_read_through_current_project_chart(
    session_client, chart_scope, create_user, workspace, kind, endpoint
):
    _, url = chart_scope
    other = Project.objects.create(
        workspace=workspace, name="其他项目", identifier="CMOTHER"
    )
    # Even membership in both projects cannot mix an object into a different route's project scope.
    ProjectMember.objects.create(project=other, member=create_user, role=20)
    item = container(other, create_user, kind)
    response = session_client.get(
        url.replace("advance-analytics-charts", endpoint),
        {"type": "work-items", kind + "_id": str(item.id)},
    )
    assert response.status_code == 404, response.content[:300]


@pytest.mark.parametrize("kind", ["cycle", "module"])
def test_daily_chart_uses_issue_creation_day_not_membership_date(
    session_client, chart_scope, create_user, workspace, kind
):
    project, url = chart_scope
    item = container(project, create_user, kind)
    state = State.objects.create(
        project=project, workspace=workspace, name="完成", group="completed"
    )
    issue = Issue.objects.create(
        project=project, workspace=workspace, name="此前创建后加入", state=state
    )
    Issue.objects.filter(pk=issue.pk).update(
        created_at=datetime(2026, 10, 9, 16, 30, tzinfo=dt_timezone.utc)
    )
    link_class, field = (
        (CycleIssue, "cycle") if kind == "cycle" else (ModuleIssue, "module")
    )
    link = link_class.objects.create(
        project=project, workspace=workspace, issue=issue, **{field: item}
    )
    link_class.objects.filter(pk=link.pk).update(
        created_at=datetime(2026, 10, 11, 4, tzinfo=dt_timezone.utc)
    )
    response = session_client.get(
        url, {"type": "work-items", kind + "_id": str(item.id)}
    )
    assert response.status_code == 200, response.content
    rows = {row["key"]: row for row in response.data["data"]}
    assert list(rows) == ["2026-10-10", "2026-10-11"], response.data
    assert (
        rows["2026-10-10"]["created_issues"]
        == rows["2026-10-10"]["completed_issues"]
        == 1
    ), response.data
    assert rows["2026-10-10"]["count"] == 1, response.data
    assert (
        rows["2026-10-11"]["created_issues"]
        == rows["2026-10-11"]["completed_issues"]
        == 0
    ), response.data


@pytest.mark.parametrize("kind", ["cycle", "module"])
def test_reversed_schedule_returns_empty_chart(
    session_client, chart_scope, create_user, kind
):
    project, url = chart_scope
    item = container(project, create_user, kind)
    if kind == "cycle":
        item.end_date = datetime(2026, 10, 8, 16, tzinfo=dt_timezone.utc)
    else:
        item.target_date = date(2026, 10, 9)
    item.save()
    response = session_client.get(
        url, {"type": "work-items", kind + "_id": str(item.id)}
    )
    assert response.status_code == 200 and response.data["data"] == [], response.content
