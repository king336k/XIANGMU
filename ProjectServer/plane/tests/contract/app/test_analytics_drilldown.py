"""Statistics drilldowns use the same authorized query as their displayed totals."""

import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from plane.db.models import Project, ProjectMember, WorkspaceMember, User, State, Issue, Cycle, Module

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def drill(workspace, create_user):
    p = Project.objects.create(workspace=workspace, name="统计明细", identifier="DRILL156")
    hidden = Project.objects.create(workspace=workspace, name="不可见项目", identifier="HIDDEN156")
    ProjectMember.objects.create(project=p, member=create_user, role=20)
    for group in ["started", "backlog", "unstarted", "completed", "cancelled"]:
        state = State.objects.create(workspace=workspace, project=p, name=group, group=group)
        Issue.objects.create(workspace=workspace, project=p, state=state, name=f"明细{group}")
    Issue.objects.create(workspace=workspace, project=hidden, name="不能泄露")
    Cycle.objects.create(workspace=workspace, project=p, name="本轮周期", owned_by=create_user)
    Module.objects.create(workspace=workspace, project=p, name="功能模块")
    c = APIClient()
    c.force_authenticate(create_user)
    return c, p, hidden, f"/api/workspaces/{workspace.slug}/advance-analytics/"


@pytest.mark.parametrize(
    "metric",
    [
        "total_users",
        "total_admins",
        "total_members",
        "total_guests",
        "total_projects",
        "total_work_items",
        "total_cycles",
        "total_intake",
    ],
)
def test_overview_card_detail_count_and_scope_match(drill, metric):
    c, p, hidden, url = drill
    args = {"tab": "overview", "project_ids": str(p.id)}
    count = c.get(url, args).data[metric]["count"]
    response = c.get(url, {**args, "detail": metric, "per_page": 20})
    assert response.status_code == 200, response.content
    assert response.data["count"] == count
    assert len(response.data["results"]) == count
    assert all("不能泄露" not in row["title"] and row["url"].startswith("/") for row in response.data["results"])
    inaccessible = c.get(url, {**args, "project_ids": str(hidden.id), "detail": metric})
    assert inaccessible.status_code == 200 and inaccessible.data["count"] == 0


@pytest.mark.parametrize(
    "metric,count",
    [
        ("total_work_items", 5),
        ("started_work_items", 1),
        ("backlog_work_items", 1),
        ("un_started_work_items", 1),
        ("completed_work_items", 1),
        ("cancelled_work_items", 1),
    ],
)
def test_work_item_card_and_paged_details(drill, metric, count):
    c, p, _, url = drill
    r = c.get(url, {"tab": "work-items", "project_ids": str(p.id), "detail": metric, "per_page": 2})
    assert r.status_code == 200, r.content
    assert r.data["count"] == count
    assert len(r.data["results"]) == min(2, count)
    if count > 2:
        second = c.get(url, {"tab": "work-items", "project_ids": str(p.id), "detail": metric, "per_page": 2, "page": 2})
        assert {row["id"] for row in r.data["results"]}.isdisjoint(row["id"] for row in second.data["results"])


@pytest.mark.parametrize(
    "params",
    [
        {"detail": "arbitrary"},
        {"detail": "total_users", "page": "bad"},
        {"detail": "total_work_items", "per_page": 1001},
    ],
)
def test_detail_rejects_invalid_input(drill, params):
    c, _, _, url = drill
    assert c.get(url, params).status_code == 400


def test_detail_respects_time_range_and_workspace_revocation(drill, workspace, create_user):
    c, p, _, url = drill
    old = Issue.objects.filter(project=p).first()
    Issue.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=60))
    args = {"tab": "work-items", "project_ids": str(p.id), "date_filter": "last_7_days"}
    count = c.get(url, args).data["total_work_items"]["count"]
    r = c.get(url, {**args, "detail": "total_work_items"})
    assert r.data["count"] == count == 4
    WorkspaceMember.objects.filter(workspace=workspace, member=create_user).update(is_active=False)
    assert c.get(url, {"detail": "total_work_items"}).status_code == 403


def test_project_peek_card_detail_keeps_project_scope(drill, workspace):
    c, p, hidden, _ = drill
    url = f"/api/workspaces/{workspace.slug}/projects/{p.id}/advance-analytics/"
    r = c.get(url, {"detail": "started_work_items", "tab": "work-items", "project_ids": str(hidden.id)})
    assert r.status_code == 200 and r.data["count"] == 0
    r = c.get(url, {"detail": "started_work_items", "tab": "work-items"})
    assert r.status_code == 200 and r.data["count"] == 1


@pytest.mark.parametrize("metric", ["total_modules", "total_pages", "total_views"])
def test_resource_bars_and_details_respect_private_content(drill, workspace, create_user, metric):
    from plane.db.models import Page, ProjectPage, IssueView

    c, p, _, url = drill
    other = User.objects.create(username="private-owner156", email="private-owner156@invalid.test")
    for owner, access, title in [(create_user, 0, "共享文档"), (other, 1, "他人私有文档")]:
        page = Page.objects.create(workspace=workspace, owned_by=owner, access=access, name=title)
        ProjectPage.objects.create(workspace=workspace, project=p, page=page)
    for owner, access, title in [(create_user, 1, "共享视图"), (other, 0, "他人私有视图")]:
        IssueView.objects.create(workspace=workspace, project=p, owned_by=owner, access=access, name=title)
    response = c.get(url, {"detail": metric, "project_ids": str(p.id)})
    assert response.status_code == 200, response.content
    assert response.data["count"] == 1
    assert all("他人私有" not in row["title"] for row in response.data["results"])
    chart = c.get(
        url.replace("/advance-analytics/", "/advance-analytics-charts/"), {"type": "projects", "project_ids": str(p.id)}
    )
    assert next(row["count"] for row in chart.data if row["key"] == metric.removeprefix("total_")) == 1


def test_status_cell_filter_and_invalid_month_do_not_silently_return_unfiltered(drill):
    c, p, _, url = drill
    r = c.get(
        url, {"tab": "work-items", "detail": "total_work_items", "state_group": "started", "project_ids": str(p.id)}
    )
    assert r.status_code == 200 and r.data["count"] == 1
    assert (
        c.get(url, {"tab": "work-items", "detail": "total_work_items", "created_month": "garbage"}).status_code == 400
    )


@pytest.mark.parametrize("axis,key", [("PRIORITY", "high"), ("STATE_GROUPS", "started")])
def test_custom_chart_slice_drills_to_exact_distinct_items(drill, axis, key):
    c, p, _, url = drill
    first = Issue.objects.filter(project=p, state__group="started").first()
    Issue.objects.filter(pk=first.pk).update(priority="high")
    response = c.get(
        url,
        {
            "tab": "work-items",
            "detail": "total_work_items",
            "project_ids": str(p.id),
            "dimension": axis,
            "dimension_value": key,
        },
    )
    assert response.status_code == 200 and response.data["count"] == 1
    assert response.data["results"][0]["id"] == str(first.id)


@pytest.mark.parametrize(
    "extra",
    [
        {"created_month": "0000-01-01"},
        {"project_ids": "not-a-uuid"},
        {"dimension": "PRIORITY"},
        {"dimension": "STATES", "dimension_value": "wrong"},
    ],
)
def test_malformed_drilldown_filters_fail_as_400(drill, extra):
    c, _, _, url = drill
    r = c.get(url, {"tab": "work-items", "detail": "total_work_items", **extra})
    assert r.status_code == 400


def test_day_bucket_only_returns_the_day_used_by_cycle_chart(drill):
    from zoneinfo import ZoneInfo
    from datetime import datetime

    c, p, _, url = drill
    item = Issue.objects.filter(project=p).first()
    Issue.objects.filter(project=p).update(created_at=datetime(2026, 11, 8, 10, tzinfo=ZoneInfo("Asia/Shanghai")))
    Issue.objects.filter(pk=item.pk).update(created_at=datetime(2026, 11, 9, 1, tzinfo=ZoneInfo("Asia/Shanghai")))
    response = c.get(
        url, {"tab": "work-items", "detail": "total_work_items", "project_ids": str(p.id), "created_day": "2026-11-09"}
    )
    assert response.data["count"] == 1


def test_unset_priority_is_literal_none_not_sql_null(drill):
    c, p, _, url = drill
    Issue.objects.filter(project=p).update(priority="none")
    r = c.get(
        url,
        {
            "tab": "work-items",
            "detail": "total_work_items",
            "project_ids": str(p.id),
            "dimension": "PRIORITY",
            "dimension_value": "none",
        },
    )
    assert r.data["count"] == 5


def test_monthly_created_chart_includes_partial_first_and_last_months(drill):
    c,p,_,url=drill
    response=c.get(url.replace('/advance-analytics/','/advance-analytics-charts/'),{'type':'work-items','project_ids':str(p.id),'date_filter':'last_30_days'})
    assert response.status_code==200
    assert sum(row['created_issues'] for row in response.data['data'])==5
    assert all(row['key'].endswith('-01') for row in response.data['data'])
