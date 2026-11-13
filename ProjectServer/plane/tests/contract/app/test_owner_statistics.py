"""Owner totals and paginated drilldowns use each surface's full authorized source."""

from uuid import uuid4
from datetime import timedelta
import pytest
from django.utils import timezone
from plane.db.models import User, Project, ProjectMember, WorkspaceMember, Issue, IssueAssignee, State
from plane.quality.models import Defect, DefectVerificationResult
from plane.tests.contract.app.test_statistics_scopes import case_plan, execute, verification

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def owners(session_client, workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="归属统计", identifier="OWNERST")
    ProjectMember.objects.create(project=project, member=create_user, role=20)
    hidden = Project.objects.create(workspace=workspace, name="不可见项目", identifier="OWNERHID")
    users = []
    for index in range(13):
        user = User.objects.create(
            username=f"statistics-owner-{index}",
            email=f"statistics-owner-{index}@test.invalid",
            display_name=f"负责人{index:02}",
        )
        users.append(user)
        WorkspaceMember.objects.create(workspace=workspace, member=user, role=15)
        ProjectMember.objects.create(project=project, member=user, role=15)
    base = f"/api/workspaces/{workspace.slug}/projects/{project.id}/quality/"
    return session_client, workspace, project, hidden, create_user, users, base


def query(owners, source="defects", metric="total", **params):
    client, _, _, _, _, _, base = owners
    return client.get(base + "owner-statistics/", {"source": source, "metric": metric, **params})


def test_defect_owner_totals_include_every_page_unassigned_departed_and_filter_intersection(owners):
    _, _, project, hidden, actor, users, _ = owners
    for user in users:
        Defect.objects.create(project=project, created_by=actor, assignee=user, title="归属缺陷")
    Defect.objects.create(project=project, created_by=actor, title="未分派")
    for index in range(25):
        Defect.objects.create(
            project=project, created_by=actor, assignee=users[0], title=f"已关闭{index}", status="closed"
        )
    Defect.objects.create(project=hidden, assignee=users[0], title="隐藏")
    Defect.objects.create(project=project, assignee=users[0], title="归档", archived_at=timezone.now())
    users[1].is_active = False
    users[1].save()
    first = query(owners)
    assert first.status_code == 200, first.content
    assert first.data["total"] == 39 and first.data["count"] == 14
    assert len(first.data["results"]) == 10
    second = query(owners, page=2)
    assert len(second.data["results"]) == 4
    rows = first.data["results"] + second.data["results"]
    departed = next(row for row in rows if row["owner_id"] == str(users[1].id))
    assert not departed["active"] and departed["count"] == 1
    group = next(row for row in rows if row["owner_id"] == str(users[0].id))
    assert group["count"] == 26 and sum(row["count"] for row in group["statuses"]) == 26
    details = query(owners, owner_id=str(users[0].id), owner_status="closed")
    assert details.data["count"] == 25 and len(details.data["results"]) == 20
    assert all(str(hidden.id) not in row["url"] for row in details.data["results"])
    assert query(owners, owner_id=str(users[0].id), status="open", owner_status="closed").data["count"] == 0
    assert query(owners, owner_id="unassigned").data["count"] == 1


def test_quality_current_latest_and_history_count_actual_executors_not_authors(owners):
    _, _, project, _, actor, users, _ = owners
    _, plan, item = case_plan(project, actor, assignee=users[0])
    execute(project, users[1], item, "failed")
    execute(project, users[2], item, "passed")
    _, archived, archived_item = case_plan(project, actor, "历史计划", archived_at=timezone.now(), assignee=users[0])
    execute(project, users[1], archived_item, "failed")
    current = query(owners, "quality", "summary_total")
    assert current.status_code == 200, current.content
    assert current.data["total"] == 1
    assert current.data["results"][0]["owner_id"] == str(users[2].id)
    assert query(owners, "quality", "summary_failed").data["total"] == 0
    history = query(owners, "quality", "execution_count")
    assert history.data["total"] == 3
    assert {row["owner_id"]: row["count"] for row in history.data["results"]} == {
        str(users[1].id): 2,
        str(users[2].id): 1,
    }
    assert query(owners, "quality", "plan_count").data["total"] == 1
    assert query(owners, "quality", "historical_plan_count").data["total"] == 2
    assert query(owners, "quality", "case_count").data["results"][0]["owner_id"] == "unassigned"


def test_manual_latest_round_and_all_execution_history_are_separate(owners):
    _, _, project, _, actor, users, _ = owners
    defect = Defect.objects.create(
        project=project,
        created_by=actor,
        assignee=users[0],
        title="人工实测",
        status="closed",
        fixed_build="v2",
        resolved_at=timezone.now(),
    )
    old = verification(project, actor, defect, 1, status="returned_test")
    current = verification(project, actor, defect, 2)
    for row, executor, result in [
        (old, users[1], "passed"),
        (current, users[1], "failed"),
        (current, users[2], "passed"),
    ]:
        DefectVerificationResult.objects.create(
            project=project,
            created_by=executor,
            verification=row,
            request_id=uuid4(),
            request_hash="x",
            result=result,
            actual_result="实测",
            evidence="证据",
        )
    data = query(owners, "quality", "manual_total").data
    assert data["total"] == 1 and data["results"][0]["owner_id"] == str(users[2].id)
    assert query(owners, "quality", "manual_execution_count").data["total"] == 3


def test_analytics_multi_owner_totals_are_distinct_and_each_collaborator_drills_all(owners):
    client, workspace, project, hidden, _, users, _ = owners
    state = State.objects.create(project=project, name="进行中", group="started")
    for index in range(27):
        issue = Issue.objects.create(project=project, name=f"多人任务{index}", state=state)
        for user in users[:2]:
            IssueAssignee.objects.create(project=project, workspace=workspace, issue=issue, assignee=user)
    Issue.objects.create(project=hidden, name="不可见任务")
    url = f"/api/workspaces/{workspace.slug}/owner-statistics/"
    args = {"source": "analytics", "metric": "total_work_items"}
    response = client.get(url, args)
    assert response.status_code == 200, response.content
    assert response.data["total"] == 27 and response.data["collaborative"]
    assert [row["count"] for row in response.data["results"]] == [27, 27]
    response = client.get(url, {**args, "owner_id": str(users[0].id), "page": 2})
    assert response.data["count"] == 27 and len(response.data["results"]) == 7
    assert client.get(url, {**args, "project_ids": str(hidden.id)}).data["total"] == 0


def test_period_ownership_uses_same_current_and_historical_querysets(owners):
    _, _, project, _, actor, users, _ = owners
    now = timezone.localdate()
    old = Defect.objects.create(project=project, created_by=actor, assignee=users[0], title="区间之外当前待办")
    Defect.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=100))
    Defect.objects.create(project=project, assignee=users[1], title="区间历史归档", archived_at=timezone.now())
    args = {"start": now.isoformat(), "end": now.isoformat()}
    assert query(owners, "period", "defects_created", **args).data["total"] == 1
    data = query(owners, "period", "current_defects", **args).data
    assert data["total"] == 1 and data["results"][0]["owner_id"] == str(users[0].id)


def test_owner_detail_status_validation_and_query_cost_do_not_scale_per_owner(owners, django_assert_max_num_queries):
    client, _, project, _, actor, users, base = owners
    for index in range(120):
        Defect.objects.create(
            project=project, created_by=actor, assignee=users[index % len(users)], title=f"缺陷{index}"
        )
    WorkspaceMember.objects.filter(workspace=project.workspace, member=users[0]).update(is_active=False)
    with django_assert_max_num_queries(18):
        response = query(owners)
    assert response.status_code == 200
    assert response.data["total"] == 120
    rows = response.data["results"] + query(owners, page=2).data["results"]
    assert not next(row for row in rows if row["owner_id"] == str(users[0].id))["active"]
    assert query(owners, owner_id="invalid").status_code == 400
    assert query(owners, per_page=101).status_code == 400
    assert query(owners, metric="not-real").status_code == 400


def test_work_list_rich_filters_are_shared_and_cannot_expand_visible_scope(owners):
    import json

    client, workspace, project, hidden, actor, users, base = owners
    state = State.objects.create(project=project, name="待办", group="unstarted")
    for name in ["keep", "discard"]:
        Issue.objects.create(project=project, name=name, state=state, priority="high" if name == "keep" else "low")
    Issue.objects.create(project=hidden, name="keep")
    filters = json.dumps({"and": [{"priority__in": ["high"]}]})
    url = f"/api/workspaces/{workspace.slug}/owner-statistics/"
    response = client.get(url, {"source": "work_items", "metric": "total_work_items", "filters": filters})
    assert response.status_code == 200, response.content
    assert response.data["total"] == 1
    detail = client.get(
        url, {"source": "work_items", "metric": "total_work_items", "filters": filters, "owner_id": "unassigned"}
    )
    assert detail.data["results"][0]["title"] == "keep"


def test_guest_owned_only_work_list_and_project_permission_boundaries(owners):
    client, workspace, project, hidden, actor, users, base = owners
    guest = users[0]
    ProjectMember.objects.filter(project=project, member=guest).update(role=5)
    WorkspaceMember.objects.filter(workspace=workspace, member=guest).update(role=5)
    Project.objects.filter(pk=project.pk).update(guest_view_all_features=False)
    state = State.objects.create(project=project, name="待办", group="unstarted")
    own = Issue(project=project, name="访客可看", state=state)
    own.save(created_by_id=guest.id)
    foreign = Issue(project=project, name="访客不可看", state=state)
    foreign.save(created_by_id=actor.id)
    client.force_authenticate(user=guest)
    url = f"/api/workspaces/{workspace.slug}/owner-statistics/"
    response = client.get(url, {"source": "work_items", "metric": "total_work_items"})
    assert response.status_code == 200 and response.data["total"] == 1, response.content
    assert query(owners, "period", "current_defects", start="2026-11-13", end="2026-11-13").status_code == 403
    assert (
        client.get(
            f"/api/workspaces/{workspace.slug}/projects/{hidden.id}/quality/owner-statistics/",
            {"source": "defects", "metric": "total"},
        ).status_code
        == 403
    )


def test_pending_current_item_goes_to_plan_owner_not_defect_technician(owners):
    _, _, project, _, actor, users, _ = owners
    _, plan, _ = case_plan(project, actor, assignee=users[0])
    response = query(owners, "quality", "summary_pending")
    assert response.data["total"] == 1
    assert response.data["results"][0]["owner_id"] == str(users[0].id)


def test_plan_and_verification_local_scope_cannot_mix_other_plans_or_projects(owners):
    _, _, project, hidden, actor, users, _ = owners
    _, selected, item = case_plan(project, actor, assignee=users[0])
    _, other, other_item = case_plan(project, actor, "其他计划", assignee=users[1])
    execute(project, users[1], item, "passed")
    execute(project, users[2], other_item, "failed")
    assert query(owners, "quality", "summary_total", plan_id=str(selected.id)).data["total"] == 1
    data = query(owners, "quality", "summary_total", plan_id=str(selected.id), owner_id=str(users[1].id)).data
    assert data["count"] == 1 and str(selected.id) in data["results"][0]["url"]
    _, foreign, _ = case_plan(hidden, actor)
    assert query(owners, "quality", "summary_total", plan_id=str(foreign.id)).status_code == 404


def test_analytics_resource_owner_uses_declared_owner_and_identity_not_creator(owners):
    from plane.db.models import Cycle, Module

    client, workspace, project, _, actor, users, _ = owners
    Project.objects.filter(pk=project.pk).update(project_lead=users[0])
    Cycle.objects.create(project=project, workspace=workspace, name="周期", owned_by=users[1])
    Module.objects.create(project=project, workspace=workspace, name="模块", lead=users[2], status="planned")
    url = f"/api/workspaces/{workspace.slug}/owner-statistics/"
    for metric, user in [("total_projects", users[0]), ("total_cycles", users[1]), ("total_modules", users[2])]:
        response = client.get(url, {"source": "analytics", "metric": metric})
        assert response.status_code == 200, response.content
        assert response.data["total"] == 1 and response.data["results"][0]["owner_id"] == str(user.id)
        detail = client.get(url, {"source": "analytics", "metric": metric, "owner_id": str(user.id)})
        assert detail.status_code == 200 and detail.data["count"] == 1, detail.content
    response = client.get(url, {"source": "analytics", "metric": "total_users"})
    assert response.status_code == 200 and response.data["total"] == 14, response.content


def test_work_statistics_link_scope_and_inactive_assignment_links(owners):
    from plane.db.models import Cycle, CycleIssue, Module, ModuleIssue

    client, workspace, project, hidden, _, users, _ = owners
    state = State.objects.create(project=project, name="待办", group="unstarted")
    cycle = Cycle.objects.create(project=project, workspace=workspace, name="范围周期", owned_by=users[0])
    module = Module.objects.create(project=project, workspace=workspace, name="范围模块", lead=users[0])
    selected = Issue.objects.create(project=project, name="范围内", state=state)
    Issue.objects.create(project=project, name="范围外", state=state)
    CycleIssue.objects.create(project=project, workspace=workspace, cycle=cycle, issue=selected)
    ModuleIssue.objects.create(project=project, workspace=workspace, module=module, issue=selected)
    IssueAssignee.objects.create(project=project, workspace=workspace, issue=selected, assignee=users[0])
    removed = IssueAssignee.objects.create(project=project, workspace=workspace, issue=selected, assignee=users[1])
    removed.delete()
    url = f"/api/workspaces/{workspace.slug}/owner-statistics/"
    for source in ["work_items", "analytics"]:
        for key, value in [("cycle_id", cycle.id), ("module_id", module.id)]:
            response = client.get(url, {"source": source, "metric": "total_work_items", key: str(value)})
            assert response.status_code == 200 and response.data["total"] == 1, response.content
            assert [row["owner_id"] for row in response.data["results"]] == [str(users[0].id)]


def test_project_member_resource_scope_and_epic_analysis_intersect(owners):
    client, workspace, project, hidden, actor, users, base = owners
    state = State.objects.create(project=project, name="待办", group="unstarted")
    from plane.db.models import IssueType

    epic = IssueType.objects.create(workspace=workspace, name="Epic", is_epic=True)
    Issue.objects.create(project=project, name="史诗", state=state, type=epic)
    Issue.objects.create(project=project, name="普通", state=state)
    response = query(owners, "analytics", "total_work_items", epic="true")
    assert response.status_code == 200 and response.data["total"] == 1, response.content
    args = {"tab": "work-items", "epic": "true"}
    card = client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/advance-analytics/", args)
    assert card.status_code == 200 and card.data["total_work_items"]["count"] == 1, card.content
    detail = client.get(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/advance-analytics/",
        {**args, "detail": "total_work_items"},
    )
    assert detail.status_code == 200 and detail.data["count"] == 1, detail.content
    members = query(owners, "analytics", "total_users")
    assert members.status_code == 200 and members.data["total"] == 14, members.content


def test_valid_empty_cycle_is_zero_and_cannot_become_missing_when_filters_remove_all_work(owners):
    from plane.db.models import Cycle

    client, workspace, project, _, _, users, base = owners
    cycle = Cycle.objects.create(project=project, workspace=workspace, name="有效空周期", owned_by=users[0])
    for url in [base + "owner-statistics/", f"/api/workspaces/{workspace.slug}/owner-statistics/"]:
        response = client.get(
            url, {"source": "work_items", "metric": "total_work_items", "cycle_id": str(cycle.id), "priority": "urgent"}
        )
        assert response.status_code == 200 and response.data["total"] == 0, response.content


def test_workspace_portfolio_exposes_visible_quality_owner_and_rejects_task_only_scope(owners):
    client, workspace, project, hidden, actor, users, base = owners
    for index in range(115):
        Defect.objects.create(project=project, assignee=users[0], title=f"全局缺陷{index}")
    Defect.objects.create(project=hidden, assignee=users[0], title="不可见缺陷")
    Defect.objects.create(project=project, assignee=users[0], title="归档缺陷", archived_at=timezone.now())
    _, plan, item = case_plan(project, actor, assignee=users[1])
    execute(project, users[2], item)
    url = f"/api/workspaces/{workspace.slug}/owner-statistics/"
    args = {"source": "analytics", "metric": "total_defects"}
    response = client.get(url, args)
    assert response.status_code == 200 and response.data["total"] == 115, response.content
    assert response.data["results"][0]["owner_id"] == str(users[0].id)
    detail = client.get(url, {**args, "owner_id": str(users[0].id), "page": 6})
    assert detail.data["count"] == 115 and len(detail.data["results"]) == 15
    assert client.get(url, {**args, "cycle_id": str(uuid4())}).status_code == 400
    for metric in ["total_test_plans", "total_test_executions"]:
        response = client.get(url, {"source": "analytics", "metric": metric})
        assert response.status_code == 200 and response.data["total"] == 1, response.content


def test_canonical_admin_needs_no_manual_memberships_but_role20_does_not_grant_global_scope(owners):
    from plane.license.models import Instance, InstanceAdmin

    client, workspace, project, hidden, actor, users, base = owners
    Defect.objects.create(project=hidden, assignee=users[0], title="管理员可见")
    ProjectMember.objects.filter(member=actor).delete()
    WorkspaceMember.objects.filter(member=actor).delete()
    instance = Instance.objects.create(
        instance_name="owners", instance_id=str(uuid4()), current_version="test", last_checked_at=timezone.now()
    )
    InstanceAdmin.objects.create(instance=instance, user=actor)
    response = client.get(
        f"/api/workspaces/{workspace.slug}/owner-statistics/", {"source": "analytics", "metric": "total_defects"}
    )
    assert response.status_code == 200 and response.data["total"] == 1, response.content
    client.force_authenticate(user=users[0])
    ProjectMember.objects.filter(project=project, member=users[0]).update(role=20)
    WorkspaceMember.objects.filter(workspace=workspace, member=users[0]).update(role=20)
    response = client.get(
        f"/api/workspaces/{workspace.slug}/owner-statistics/", {"source": "analytics", "metric": "total_defects"}
    )
    assert response.status_code == 200 and response.data["total"] == 0, response.content


def test_defect_date_source_archive_owner_filters_all_intersect_without_join_duplicates(owners):
    from datetime import datetime, timezone as utc
    from plane.quality.models import SourceLink

    _, _, project, hidden, actor, users, _ = owners
    defect = Defect.objects.create(
        project=project, assignee=users[0], title="日期边界", status="closed", archived_at=timezone.now()
    )
    Defect.objects.filter(pk=defect.pk).update(created_at=datetime(2026, 11, 12, 16, 0, tzinfo=utc.utc))
    for index in range(3):
        SourceLink.objects.create(
            project=project,
            defect=defect,
            source_system="daq",
            source_instance="test",
            record_type="evidence",
            record_id=str(index),
        )
    params = {
        "archived": "true",
        "status": "closed",
        "source_system": "daq",
        "start": "2026-11-13",
        "end": "2026-11-13",
    }
    response = query(owners, **params)
    assert response.status_code == 200 and response.data["total"] == 1, response.content
    detail = query(owners, owner_id=str(users[0].id), owner_status="closed", **params)
    assert detail.data["count"] == 1 and detail.data["results"][0]["id"] == str(defect.id)
    assert query(owners, **{**params, "start": "2026-11-12", "end": "2026-11-12"}).data["total"] == 0


@pytest.mark.parametrize("mode", ["manual", "cases"])
def test_explicit_returned_verification_uses_its_own_round_without_changing_global_current(owners, mode):
    _, _, project, hidden, actor, users, _ = owners
    defect = Defect.objects.create(
        project=project, title="退回补测", status="resolved", fixed_build="v2", resolved_at=timezone.now()
    )
    plan = item = None
    if mode == "cases":
        _, plan, item = case_plan(project, actor, assignee=users[0])
    old = verification(project, actor, defect, 1, mode=mode, plan=plan, status="returned_test")
    if mode == "manual":
        DefectVerificationResult.objects.create(
            project=project,
            created_by=users[1],
            verification=old,
            request_id=uuid4(),
            request_hash="x",
            result="failed",
            actual_result="旧轮实测",
            evidence="证据",
        )
    else:
        execute(project, users[1], item, "failed", round_no=1)
        execute(project, users[2], item, "passed", round_no=2)
    prefix = "manual" if mode == "manual" else "summary"
    global_count = query(owners, "quality", prefix + "_total").data["total"]
    response = query(owners, "quality", prefix + "_failed", verification_id=str(old.id))
    assert response.status_code == 200 and response.data["total"] == 1, response.content
    assert response.data["results"][0]["owner_id"] == str(users[1].id)
    assert query(owners, "quality", prefix + "_total").data["total"] == global_count
    foreign_defect = Defect.objects.create(
        project=hidden, title="外项目轮次", status="resolved", fixed_build="v2", resolved_at=timezone.now()
    )
    foreign = verification(hidden, actor, foreign_defect, 1)
    assert query(owners, "quality", prefix + "_total", verification_id=str(foreign.id)).status_code == 404
