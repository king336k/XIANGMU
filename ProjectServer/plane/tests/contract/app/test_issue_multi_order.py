"""Issue sorting composes on the full authorized queryset before every page."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ParseError

from plane.db.models import (
    Cycle,
    CycleIssue,
    Estimate,
    EstimatePoint,
    Issue,
    Label,
    Module,
    ModuleIssue,
    Project,
    ProjectMember,
    State,
    User,
)
from plane.utils.order_queryset import ISSUE_ORDER_BY_ALLOWLIST, order_issue_queryset, sanitize_order_by
from plane.utils.paginator import Cursor, GroupedOffsetPaginator, OffsetPaginator, SubGroupedOffsetPaginator

pytestmark = [pytest.mark.contract, pytest.mark.django_db]


@pytest.fixture
def ordered_issues(workspace, create_user):
    project = Project.objects.create(workspace=workspace, name="Combined order", identifier="MORDER")
    ProjectMember.objects.create(project=project, workspace=workspace, member=create_user, role=20)
    states = [
        State.objects.create(project=project, workspace=workspace, name=name, group=group)
        for name, group in [("Alpha", "started"), ("Beta", "backlog"), ("Gamma", "unstarted")]
    ]
    priorities = ["none", "low", "medium", "high", "urgent"]
    rows = []
    for index in range(45):
        rows.append(
            Issue.objects.create(
                project=project,
                workspace=workspace,
                name=f"Row {index:02}",
                created_by=create_user,
                state=states[index % 3],
                priority=priorities[(index // 3) % 5],
                target_date=None if index % 4 == 0 else date(2026, 11, 1) + timedelta(days=index % 7),
            )
        )
    # Equal timestamps force the final ID tie-breaker to matter across pages.
    Issue.objects.filter(project=project).update(created_at=timezone.now().replace(microsecond=0))
    return project, list(Issue.objects.filter(project=project).select_related("state"))


def expected_ids(rows):
    return [
        str(row.id)
        for row in sorted(
            rows,
            key=lambda row: (
                row.state.name,
                ["urgent", "high", "medium", "low", "none"].index(row.priority),
                row.target_date is None,
                -row.target_date.toordinal() if row.target_date else 0,
                str(row.id),
            ),
        )
    ]


@pytest.mark.parametrize("group_by,sub_group_by", [(None, None), ("state_id", None), ("state_id", "priority")])
def test_all_paginator_modes_preserve_secondary_keys_across_every_page(ordered_issues, group_by, sub_group_by):
    project, rows = ordered_issues
    queryset, ordering = order_issue_queryset(
        Issue.objects.filter(project=project), "state__name,-priority,-target_date"
    )
    kwargs = {"queryset": queryset, "order_by": ordering}
    cls = OffsetPaginator
    if group_by:
        cls = SubGroupedOffsetPaginator if sub_group_by else GroupedOffsetPaginator
        kwargs.update(group_by_field_name=group_by, group_by_fields=[], count_filter=Q())
    if sub_group_by:
        kwargs.update(sub_group_by_field_name=sub_group_by, sub_group_by_fields=[])
    paginator = cls(**kwargs)
    buckets = {}
    for page in range(20):
        result = paginator.get_result(limit=4, cursor=Cursor(4, page))
        for row in result.results:
            bucket = (row.state_id if group_by else None, row.priority if sub_group_by else None)
            buckets.setdefault(bucket, []).append(str(row.id))
        if not result.next.has_results:
            break
    assert sum(map(len, buckets.values())) == 45
    assert len({identifier for identifiers in buckets.values() for identifier in identifiers}) == 45
    for bucket, identifiers in buckets.items():
        selected = [
            row
            for row in rows
            if (not group_by or row.state_id == bucket[0]) and (not sub_group_by or row.priority == bucket[1])
        ]
        assert identifiers == expected_ids(selected)


@pytest.mark.parametrize("group_by,sub_group_by", [(None, None), ("state_id", None), ("state_id", "priority")])
def test_api_combined_filters_order_full_scope_and_keep_project_permissions(
    session_client, ordered_issues, workspace, group_by, sub_group_by
):
    project, rows = ordered_issues
    other = Project.objects.create(workspace=workspace, name="Hidden", identifier="ORDHIDE")
    Issue.objects.create(project=other, workspace=workspace, name="Never exposed", priority="urgent")
    endpoint = f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/"
    selected = [row for row in rows if row.priority in {"urgent", "high"} and row.state_id == rows[0].state_id]
    seen = []
    for page in range(10):
        params = {
            "order_by": "state__name,-priority,-target_date",
            "per_page": 2,
            "cursor": f"2:{page}:0",
            "priority": "urgent,high",
            "state": str(rows[0].state_id),
        }
        if group_by:
            params["group_by"] = group_by
        if sub_group_by:
            params["sub_group_by"] = sub_group_by
        response = session_client.get(endpoint, params)
        assert response.status_code == 200, response.data
        assert response.data["total_count"] == len(selected)
        results = response.data["results"]
        if group_by:
            groups = [group["results"] for group in results.values()]
            if sub_group_by:
                groups = [subgroup["results"] for group in groups for subgroup in group.values()]
            results = [row for group in groups for row in group]
        seen.extend(str(row["id"]) for row in results)
        if not response.data["next_page_results"]:
            break
    if sub_group_by:
        assert len(seen) == len(set(seen)) == len(selected)
        for priority in {"urgent", "high"}:
            ids = {str(row.id) for row in selected if row.priority == priority}
            assert [identifier for identifier in seen if identifier in ids] == expected_ids(
                [row for row in selected if row.priority == priority]
            )
    else:
        assert seen == expected_ids(selected)
    hidden = endpoint.replace(str(project.id), str(other.id))
    assert session_client.get(hidden, {"order_by": "state__name,-priority"}).status_code == 403


@pytest.mark.parametrize(
    "value",
    [
        "priority,created_by__password",
        "priority,--created_at",
        "priority,",
        ",priority",
        "priority,priority",
        "priority,-priority",
        "priority;DROP TABLE,created_at",
        "created_at,updated_at,sequence_id,sort_order,target_date,start_date",
    ],
)
def test_multisort_rejects_invalid_fields_duplicates_and_excess_without_orm_access(value):
    with pytest.raises(ParseError):
        order_issue_queryset(Issue.objects.none(), value)
    # Other endpoints retain their historical single-field fallback contract.
    assert sanitize_order_by(value, ISSUE_ORDER_BY_ALLOWLIST) == "-created_at"


@pytest.mark.parametrize("field", ["priority", "-priority", "state__group", "-state__group"])
def test_multisort_primary_semantics_match_existing_single_field(ordered_issues, field):
    project, _ = ordered_issues
    first, first_order = order_issue_queryset(Issue.objects.filter(project=project), field)
    combined, combined_order = order_issue_queryset(Issue.objects.filter(project=project), field + ",sequence_id")
    single = list(OffsetPaginator(first, order_by=first_order).get_result(limit=100).results)
    multi = list(OffsetPaginator(combined, order_by=combined_order).get_result(limit=100).results)
    attribute = "priority" if "priority" in field else "state_id"

    def runs(values):
        result = []
        for row in values:
            value = getattr(row, attribute)
            if not result or result[-1] != value:
                result.append(value)
        return result

    assert runs(single) == runs(multi)


def test_multiple_name_columns_use_independent_minima_without_row_multiplication(
    ordered_issues, workspace, session_client
):
    project, rows = ordered_issues
    labels = [Label.objects.create(workspace=workspace, project=project, name=name) for name in ["Zulu", "Alpha"]]
    users = [
        User.objects.create(email=f"{uuid4()}@order.test", username=str(uuid4()), first_name=name)
        for name in ["Zoe", "Amy"]
    ]
    modules = [Module.objects.create(workspace=workspace, project=project, name=name) for name in ["Yankee", "Beta"]]
    for index, row in enumerate(rows):
        if index % 3:
            row.labels.add(*labels, through_defaults={"project": project, "workspace": workspace})
            row.assignees.add(*users, through_defaults={"project": project, "workspace": workspace})
            for module in modules:
                ModuleIssue.objects.create(workspace=workspace, project=project, issue=row, module=module)
    queryset, ordering = order_issue_queryset(
        Issue.objects.filter(project=project),
        "labels__name,assignees__first_name,issue_module__module__name,-sequence_id",
    )
    seen = []
    for page in range(12):
        result = OffsetPaginator(queryset, order_by=ordering).get_result(limit=4, cursor=Cursor(4, page))
        seen.extend(str(row.id) for row in result.results)
        if not result.next.has_results:
            break
    assigned_ids = {row.id for index, row in enumerate(rows) if index % 3}
    expected = sorted(rows, key=lambda row: (row.id not in assigned_ids, -row.sequence_id))
    assert seen == [str(row.id) for row in expected]
    assert len(seen) == len(set(seen)) == 45
    expected_rows = [row for index, row in enumerate(rows) if index % 3]
    for grouped in [False, True]:
        collected = []
        for page in range(12):
            params = {
                "order_by": "labels__name,assignees__first_name,issue_module__module__name,-sequence_id",
                "labels": ",".join(str(label.id) for label in labels),
                "assignees": ",".join(str(user.id) for user in users),
                "per_page": 4,
                "cursor": f"4:{page}:0",
            }
            if grouped:
                params["group_by"] = "state_id"
            response = session_client.get(f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/", params)
            assert response.status_code == 200, response.data
            results = response.data["results"]
            if grouped:
                results = [row for group in results.values() for row in group["results"]]
            collected.extend(str(row["id"]) for row in results)
            if not response.data["next_page_results"]:
                break
        assert len(collected) == len(set(collected)) == len(expected_rows)


@pytest.mark.parametrize("value", ["priority,created_by__password", "state__name,--target_date", "name,not_a_field"])
def test_api_rejects_unsafe_multisort_with_400(session_client, ordered_issues, workspace, value):
    project, _ = ordered_issues
    response = session_client.get(
        f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/", {"order_by": value}
    )
    assert response.status_code == 400, response.data


@pytest.mark.parametrize("descending", [False, True])
def test_date_nulls_are_last_in_both_directions_and_five_columns_are_accepted(ordered_issues, descending):
    project, rows = ordered_issues
    direction = "-" if descending else ""
    queryset, ordering = order_issue_queryset(
        Issue.objects.filter(project=project), f"{direction}target_date,state__name,-priority,sequence_id,updated_at"
    )
    result = list(OffsetPaginator(queryset, order_by=ordering).get_result(limit=100).results)
    missing = [row.target_date is None for row in result]
    assert missing == sorted(missing)
    dates = [row.target_date for row in result if row.target_date]
    assert dates == sorted(dates, reverse=descending)
    assert len(result) == len(rows) == 45


@pytest.mark.parametrize("sort", ["issue_cycle__cycle__name", "estimate_point__key", "name"])
def test_additional_native_columns_have_real_allowlisted_model_paths(ordered_issues, workspace, create_user, sort):
    project, rows = ordered_issues
    cycle = Cycle.objects.create(workspace=workspace, project=project, name="Cycle A", owned_by=create_user)
    estimate = Estimate.objects.create(workspace=workspace, project=project, name="Points")
    point = EstimatePoint.objects.create(workspace=workspace, project=project, estimate=estimate, key=2, value="M")
    for row in rows[:3]:
        CycleIssue.objects.create(workspace=workspace, project=project, cycle=cycle, issue=row)
        Issue.objects.filter(pk=row.pk).update(estimate_point=point)
    queryset, ordering = order_issue_queryset(Issue.objects.filter(project=project), sort + ",-sequence_id")
    result = list(OffsetPaginator(queryset, order_by=ordering).get_result(limit=100).results)
    assert len(result) == len({row.id for row in result}) == 45
    if sort == "name":
        assert [row.name for row in result] == sorted(row.name for row in rows)
    else:
        assert {row.id for row in result[:3]} == {row.id for row in rows[:3]}


def test_m2m_group_and_subgroup_do_not_lose_or_repeat_matches_across_pages(ordered_issues, workspace, session_client):
    project, rows = ordered_issues
    labels = [Label.objects.create(workspace=workspace, project=project, name=name) for name in ["L-A", "L-B"]]
    people = [
        User.objects.create(email=f"{uuid4()}@order.test", username=str(uuid4()), first_name=name)
        for name in ["First", "Second"]
    ]
    for row in rows:
        row.labels.add(*labels, through_defaults={"project": project, "workspace": workspace})
        row.assignees.add(*people, through_defaults={"project": project, "workspace": workspace})
    groups = {}
    for page in range(12):
        response = session_client.get(
            f"/api/workspaces/{workspace.slug}/projects/{project.id}/issues/",
            {
                "order_by": "labels__name,assignees__first_name,-priority,-target_date",
                "group_by": "labels__id",
                "sub_group_by": "assignees__id",
                "per_page": 4,
                "cursor": f"4:{page}:0",
                "labels": ",".join(str(row.id) for row in labels),
                "assignees": ",".join(str(row.id) for row in people),
            },
        )
        assert response.status_code == 200, response.data
        for label_id, group in response.data["results"].items():
            for person_id, subgroup in group["results"].items():
                groups.setdefault((label_id, person_id), []).extend(str(row["id"]) for row in subgroup["results"])
        if not response.data["next_page_results"]:
            break
    assert len(groups) == 4
    for identifiers in groups.values():
        assert len(identifiers) == len(set(identifiers)) == 45
        expected = sorted(
            rows,
            key=lambda row: (
                ["urgent", "high", "medium", "low", "none"].index(row.priority),
                row.target_date is None,
                -row.target_date.toordinal() if row.target_date else 0,
                str(row.id),
            ),
        )
        assert identifiers == [str(row.id) for row in expected]
