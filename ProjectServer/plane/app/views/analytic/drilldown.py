"""Bounded details share the exact authorized query used by analytics cards."""

from django.db.models import Q
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from django.db.models.functions import TruncDate
from plane.utils.build_chart import get_x_axis_field
from rest_framework import serializers
from rest_framework.response import Response
from plane.db.models import Project, Issue, Cycle, Module, ProjectPage, IssueView

STATES = {
    "started_work_items": "started",
    "backlog_work_items": "backlog",
    "un_started_work_items": "unstarted",
    "completed_work_items": "completed",
    "cancelled_work_items": "cancelled",
}
METRICS = [
    "total_users",
    "total_admins",
    "total_members",
    "total_guests",
    "total_projects",
    "total_work_items",
    "total_cycles",
    "total_intake",
    "total_modules",
    "total_pages",
    "total_views",
    *STATES,
]


class DetailQuery(serializers.Serializer):
    detail = serializers.ChoiceField(choices=METRICS)
    page = serializers.IntegerField(min_value=1, default=1)
    per_page = serializers.IntegerField(min_value=1, max_value=100, default=20)
    state_group = serializers.ChoiceField(
        choices=["started", "backlog", "unstarted", "completed", "cancelled"], required=False
    )
    priority = serializers.ChoiceField(choices=["urgent", "high", "medium", "low", "none"], required=False)
    assignee_id = serializers.UUIDField(required=False)
    unassigned = serializers.BooleanField(default=False)
    created_day = serializers.DateField(required=False)
    dimension = serializers.ChoiceField(choices=list(get_x_axis_field()), required=False)
    dimension_value = serializers.CharField(max_length=100, required=False)
    group_dimension = serializers.ChoiceField(choices=list(get_x_axis_field()), required=False)
    group_value = serializers.CharField(max_length=100, required=False)
    created_month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])-01$", required=False)

    def validate_created_month(self, value):
        parsed = serializers.DateField().run_validation(value)
        if parsed.year >= 9999:
            raise serializers.ValidationError("月份超出允许范围。")
        return value


def analytics_work_queryset(view, queryset=None):
    """One work-item scope for analytics cards, charts, existing details and owner breakdowns."""
    from plane.db.models import CycleIssue, ModuleIssue

    rows = queryset if queryset is not None else Issue.issue_objects.filter(**view.filters["base_filters"])
    params = view.request.query_params
    if params.get("epic") is not None:
        rows = (
            rows.filter(type__is_epic=True)
            if serializers.BooleanField().run_validation(params["epic"])
            else rows.filter(Q(type__isnull=True) | Q(type__is_epic=False))
        )
    for parameter, model, link, relation in [
        ("cycle_id", Cycle, CycleIssue, "cycle"),
        ("module_id", Module, ModuleIssue, "module"),
    ]:
        if not params.get(parameter):
            continue
        from django.shortcuts import get_object_or_404

        obj = get_object_or_404(
            model,
            pk=serializers.UUIDField().run_validation(params[parameter]),
            project_id__in=Project.objects.filter(**view.filters["project_filters"]).values("pk"),
        )
        rows = rows.filter(
            project_id=obj.project_id,
            pk__in=link.objects.filter(**{relation: obj, "project_id": obj.project_id}).values("issue_id"),
        )
    return rows


def work_queries(query):
    return {"total_work_items": query, **{key: query.filter(state__group=value) for key, value in STATES.items()}}


def resource_queries(view):
    base = view.filters["base_filters"]
    return {
        "total_modules": Module.objects.filter(**base),
        "total_pages": ProjectPage.objects.filter(**base, page__deleted_at__isnull=True).filter(
            Q(page__access=0) | Q(page__owned_by=view.request.user)
        ),
        "total_views": IssueView.objects.filter(**base).filter(Q(access=1) | Q(owned_by=view.request.user)),
    }


def overview_queries(view):
    members = view.member_queryset()
    base = view.filters["base_filters"]
    return {
        "total_users": members,
        "total_admins": members.filter(role=20),
        "total_members": members.filter(role=15),
        "total_guests": members.filter(role=5),
        "total_projects": Project.objects.filter(**view.filters["project_filters"]),
        "total_work_items": analytics_work_queryset(view),
        "total_cycles": Cycle.objects.filter(**base),
        "total_intake": analytics_work_queryset(
            view, Issue.objects.filter(**base, issue_intake__status__in=[-2, -1, 0, 1, 2])
        ).distinct(),
        **resource_queries(view),
    }


def detail_response(view, queries):
    schema = DetailQuery(data=view.request.query_params)
    schema.is_valid(raise_exception=True)
    value = schema.validated_data
    metric = value["detail"]
    if metric not in queries:
        raise serializers.ValidationError({"detail": "此统计页不支持该明细类型。"})
    query = queries[metric].distinct()
    if metric == "total_work_items" or metric in STATES:
        if value.get("state_group"):
            query = query.filter(state__group=value["state_group"])
        if value.get("priority"):
            query = query.filter(priority=value["priority"])
        if value.get("assignee_id"):
            query = query.filter(
                issue_assignee__assignee_id=value["assignee_id"], issue_assignee__deleted_at__isnull=True
            ).distinct()
        if value.get("unassigned"):
            query = query.filter(assignees__isnull=True)
        if value.get("created_day"):
            from plane.utils.date_utils import china_date_filter

            query = query.filter(**china_date_filter(value["created_day"], value["created_day"]))
        if value.get("created_month"):
            start = date.fromisoformat(value["created_month"])
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            zone = ZoneInfo("Asia/Shanghai")
            query = query.filter(
                created_at__gte=datetime.combine(start, datetime.min.time(), tzinfo=zone),
                created_at__lt=datetime.combine(end, datetime.min.time(), tzinfo=zone),
            )
    for axis_key, value_key in [("dimension", "dimension_value"), ("group_dimension", "group_value")]:
        if axis_key not in value:
            continue
        if value_key not in value or metric != "total_work_items":
            raise serializers.ValidationError({value_key: "请选择统计分类。"})
        axis, key = value[axis_key], value[value_key]
        field, _, extra = get_x_axis_field()[axis]
        query = query.filter(**(extra or {}))
        if axis in {"CREATED_AT", "COMPLETED_AT"}:
            column = "created_at" if axis == "CREATED_AT" else "completed_at"
            field = f"drill_{column}"
            query = query.annotate(**{field: TruncDate(column, tzinfo=ZoneInfo("Asia/Shanghai"))})
        if key.lower() == "none" and axis != "PRIORITY":
            query = query.filter(**{f"{field}__isnull": True})
        else:
            if axis in {"STATES", "LABELS", "ASSIGNEES", "CYCLES", "MODULES", "CREATED_BY"}:
                key = serializers.UUIDField().run_validation(key)
            if axis in {"START_DATE", "TARGET_DATE", "CREATED_AT", "COMPLETED_AT"}:
                key = serializers.DateField().run_validation(key)
            query = query.filter(**{field: key})
        query = query.distinct()
    period = view.filters["analytics_date_range"]
    if period:
        query = query.filter(created_at__gte=period["current"]["gte"], created_at__lte=period["current"]["lte"])
    query = query.order_by("-created_at", "-id")
    count = query.count()
    offset = (value["page"] - 1) * value["per_page"]
    user_metric = metric in {"total_users", "total_admins", "total_members", "total_guests"}
    query = (
        query.select_related("member")
        if user_metric
        else query.select_related("project", "page")
        if metric == "total_pages"
        else query.select_related("project")
        if metric != "total_projects"
        else query
    )
    rows = []
    root = f"/{view._workspace_slug}"
    for item in query[offset : offset + value["per_page"]]:
        if user_metric:
            user = item.member
            row = {
                "id": str(user.id),
                "title": user.display_name or user.username,
                "kind": "成员",
                "subtitle": {20: "管理员", 15: "成员", 5: "访客"}.get(item.role, "成员"),
                "url": f"{root}/profile/{user.id}/",
            }
        elif metric == "total_projects":
            row = {
                "id": str(item.id),
                "title": item.name,
                "kind": "项目",
                "subtitle": item.identifier,
                "url": f"{root}/p/{item.identifier}/issues/",
            }
        else:
            project = item.project
            prefix = f"{root}/p/{project.identifier}"
            if isinstance(item, Cycle):
                url, kind = f"{prefix}/cycles/{item.id}/", "周期"
            elif isinstance(item, Module):
                url, kind = f"{prefix}/modules/{item.id}/", "模块"
            elif isinstance(item, ProjectPage):
                url, kind = f"{prefix}/pages/{item.page_id}/", "文档"
            elif isinstance(item, IssueView):
                url, kind = f"{prefix}/views/{item.id}/", "视图"
            else:
                url, kind = f"{root}/browse/{project.identifier}-{item.sequence_id}/", "工作项"
            row = {
                "id": str(item.id),
                "project_id": str(project.id),
                "title": item.page.name if isinstance(item, ProjectPage) else item.name,
                "kind": kind,
                "subtitle": project.name,
                "url": url,
            }
        rows.append(row)
    return Response({"count": count, "results": rows, "page": value["page"], "per_page": value["per_page"]})
