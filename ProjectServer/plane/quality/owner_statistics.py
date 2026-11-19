"""Paged owner attribution over the exact authorized sources used by statistic cards."""

from types import SimpleNamespace
from collections import Counter
from django.db.models import F, Q, Count, OuterRef, Subquery, Value, UUIDField, CharField, Case, When, FilteredRelation
from django.db.models.functions import Coalesce, Cast
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.db.models import Project, ProjectMember, WorkspaceMember, User, Issue
from plane.utils.date_utils import get_analytics_filters
from .models import (
    Defect, TestCase, TestPlan, PlanItem, TestExecution, DefectVerificationResult,
    DefectVerification, DefectVerificationCase, DefectVerificationCaseExecution,
)
from .permissions import is_administrator


class OwnerQuery(serializers.Serializer):
    source = serializers.ChoiceField(choices=["defects", "quality", "period", "analytics", "work_items"])
    metric = serializers.CharField(max_length=60)
    owner_id = serializers.CharField(max_length=50, required=False)
    owner_status = serializers.CharField(max_length=40, required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    per_page = serializers.IntegerField(min_value=1, max_value=100, required=False)

    def validate_owner_id(self, value):
        return value if value == "unassigned" else str(serializers.UUIDField().run_validation(value))


def specification(query, owner, status, kind, basis, collaborative=False):
    return {
        "query": query,
        "owner": owner,
        "status": status,
        "kind": kind,
        "ownership_basis": basis,
        "collaborative": collaborative,
    }


def quality_queries(project, params=None):
    from .views import current_plans, current_verifications

    params = params or {}
    plans = current_plans(project)
    plan_id = params.get("plan_id")
    verification_id = params.get("verification_id")
    if plan_id:
        plan = get_object_or_404(TestPlan, pk=serializers.UUIDField().run_validation(plan_id), project=project)
        plans = TestPlan.objects.filter(pk=plan.pk)
    if verification_id:
        verification = get_object_or_404(
            DefectVerification, pk=serializers.UUIDField().run_validation(verification_id), project=project
        )
        plans = TestPlan.objects.filter(project=project, pk=verification.plan_id)
    executions = TestExecution.objects.filter(project=project)
    case_executions = DefectVerificationCaseExecution.objects.filter(project=project, source_execution__isnull=True)
    manuals = DefectVerificationResult.objects.filter(project=project)
    if plan_id:
        executions = executions.filter(item__plan_id=plan_id)
        case_executions = case_executions.filter(item__verification__plan_id=plan_id)
        manuals = manuals.none()
    if verification_id:
        manuals = manuals.filter(verification_id=verification_id)
        executions = executions.filter(item__plan_id=verification.plan_id)
        case_executions = case_executions.filter(item__verification_id=verification_id)
    defects = Defect.objects.filter(project=project, archived_at__isnull=True)
    plan_basis = "按计划当前负责人归属；历史计划包含已归档计划。"
    result = {
        "case_count": specification(
            TestCase.objects.filter(project=project, archived_at__isnull=True, trashed_at__isnull=True),
            None,
            "priority",
            "case",
            "用例库没有负责人字段，保留为未指派；不以创建人替代负责人。",
        ),
        "plan_count": specification(plans, "assignee_id", "status", "plan", plan_basis),
        "historical_plan_count": specification(
            TestPlan.objects.filter(project=project), "assignee_id", "status", "plan", plan_basis
        ),
        "execution_count": specification(
            executions,
            "created_by_id",
            "result",
            "execution",
            "全部历史用例执行，按每次真实执行人归属，不按计划创建人或当前负责人重算。",
        ),
        "case_execution_count": specification(
            case_executions,
            "created_by_id",
            "result",
            "case_execution",
            "缺陷回归用例执行按实际操作人归属；管理员代执行保留管理员为实际操作人。",
        ),
        "manual_execution_count": specification(
            manuals, "created_by_id", "result", "manual_execution", "全部历史人工实测，按每次真实提交人归属。"
        ),
        "open_defects": specification(
            defects.exclude(status="closed"), "assignee_id", "status", "defect", "按缺陷当前负责人归属。"
        ),
        "closed_defects": specification(
            defects.filter(status="closed"), "assignee_id", "status", "defect", "按缺陷当前负责人归属。"
        ),
    }
    latest = (
        TestExecution.objects.filter(item_id=OuterRef("pk"))
        .filter(
            Q(item__plan__managed=False, item__plan__defect_verification__isnull=True)
            | Q(round_no=OuterRef("plan__round_no"))
        )
        .order_by("-created_at", "-id")
    )
    # Avoid a join to all historical executions when deciding whether the current round is pending.
    if verification_id:
        latest = TestExecution.objects.filter(item_id=OuterRef("pk"), round_no=verification.round_no).order_by(
            "-created_at", "-id"
        )
    case_verification = (
        verification if verification_id else
        getattr(plan, "defect_verification", None) if plan_id else None
    )
    if case_verification and case_verification.mode == "cases" and case_verification.case_items.exists():
        latest_round_execution = DefectVerificationCaseExecution.objects.filter(item_id=OuterRef("pk")).order_by(
            "-created_at", "-id"
        )
        items = DefectVerificationCase.objects.filter(verification=case_verification).annotate(
            latest_execution=Subquery(latest_round_execution.values("pk")[:1]),
            owner_result=Coalesce(Subquery(latest_round_execution.values("result")[:1]), Value("pending")),
            owner_executor=Case(
                When(latest_execution__isnull=True, then=F("verification__plan__assignee_id")),
                default=Subquery(latest_round_execution.values("created_by_id")[:1]),
                output_field=UUIDField(),
            ),
        )
        item_kind = "verification_case"
    else:
        items = PlanItem.objects.filter(plan__in=plans).annotate(
            latest_execution=Subquery(latest.values("pk")[:1]),
            owner_result=Coalesce(Subquery(latest.values("result")[:1]), Value("pending")),
            owner_executor=Case(
                When(latest_execution__isnull=True, then=F("plan__assignee_id")),
                default=Subquery(latest.values("created_by_id")[:1]),
                output_field=UUIDField(),
            ),
        )
        item_kind = "item"
    case_rounds = current_verifications(project).filter(mode="cases")
    if verification_id:
        case_rounds = DefectVerification.objects.filter(project=project, pk=verification_id, mode="cases")
    if plan_id:
        case_rounds = DefectVerification.objects.filter(project=project, plan_id=plan_id, mode="cases")
    latest_case_execution = DefectVerificationCaseExecution.objects.filter(
        item_id=OuterRef("pk"), source_execution__isnull=True
    ).order_by("-created_at", "-id")
    case_round_items = DefectVerificationCase.objects.filter(
        verification__in=case_rounds, source_plan_item__isnull=True
    ).annotate(
        latest_execution=Subquery(latest_case_execution.values("pk")[:1]),
        owner_result=Coalesce(Subquery(latest_case_execution.values("result")[:1]), Value("pending")),
        owner_executor=Case(
            When(latest_execution__isnull=True, then=F("verification__plan__assignee_id")),
            default=Subquery(latest_case_execution.values("created_by_id")[:1]),
            output_field=UUIDField(),
        ),
    )
    latest_manual = DefectVerificationResult.objects.filter(verification_id=OuterRef("pk")).order_by(
        "-created_at", "-id"
    )
    manual_scope = current_verifications(project)
    if verification_id:
        manual_scope = DefectVerification.objects.filter(project=project, pk=verification.pk)
    manual_rounds = manual_scope.filter(mode="manual").annotate(
        owner_result=Coalesce(Subquery(latest_manual.values("result")[:1]), Value("pending")),
        owner_executor=Case(
            When(owner_result="pending", then=F("plan__assignee_id")),
            default=Subquery(latest_manual.values("created_by_id")[:1]), output_field=UUIDField(),
        ),
    )
    if verification_id:
        manual_rounds = manual_rounds.filter(pk=verification_id)
    if plan_id:
        manual_rounds = manual_rounds.none()
    for prefix, rows, kind, basis in [
        (
            "summary",
            items,
            item_kind,
            (
                "指定计划/验证轮次的每条最新结果按真实执行人归属；未执行归计划负责人。"
                if plan_id or verification_id
                else "当前有效计划本轮每条最新结果按真实执行人归属；未执行条目归当前计划负责人。"
            ),
        ),
        (
            "verification_case",
            case_round_items,
            "verification_case",
            "缺陷回归本轮快照用例按最新实测结果归属实际执行人；未执行条目归指派测试员。",
        ),
        (
            "manual",
            manual_rounds,
            "verification",
            (
                "指定人工验证轮次按最新实际测试人归属；未执行时归指派测试员。"
                if verification_id
                else "当前有效人工验证轮次按本轮最新实际测试人归属；未执行时归指派测试员。"
            ),
        ),
    ]:
        for suffix in ["total", "executed", "passed", "failed", "blocked", "inconclusive", "skipped", "pending"]:
            selected = (
                rows
                if suffix == "total"
                else rows.exclude(owner_result="pending")
                if suffix == "executed"
                else rows.filter(owner_result=suffix)
            )
            result[f"{prefix}_{suffix}"] = specification(selected, "owner_executor", "owner_result", kind, basis)
    if item_kind == "item":
        snapshots = DefectVerificationCase.objects.filter(verification__in=case_rounds)
        latest_snapshot_execution = DefectVerificationCaseExecution.objects.filter(item_id=OuterRef("pk")).order_by("-created_at", "-id")
        snapshots = snapshots.annotate(
            latest_execution=Subquery(latest_snapshot_execution.values("pk")[:1]),
            owner_result=Coalesce(Subquery(latest_snapshot_execution.values("result")[:1]), Value("pending")),
            owner_executor=Case(
                When(latest_execution__isnull=True, then=F("verification__plan__assignee_id")),
                default=Subquery(latest_snapshot_execution.values("created_by_id")[:1]), output_field=UUIDField(),
            ),
        )
        unmapped = items.exclude(pk__in=DefectVerificationCase.objects.filter(source_plan_item__isnull=False).values("source_plan_item_id"))
        for suffix in ["total", "executed", "passed", "failed", "blocked", "inconclusive", "skipped", "pending"]:
            parts = []
            for rows, kind in [(unmapped, "item"), (snapshots, "verification_case")]:
                selected = rows if suffix == "total" else rows.exclude(owner_result="pending") if suffix == "executed" else rows.filter(owner_result=suffix)
                parts.append(specification(selected, "owner_executor", "owner_result", kind, result["summary_" + suffix]["ownership_basis"]))
            result["summary_" + suffix] = {"parts": parts}
    result["execution_count"] = {"parts": [result["execution_count"], result["case_execution_count"]]}
    result["manual_accepted"] = specification(
        manual_rounds.filter(status="accepted"),
        "owner_executor",
        "owner_result",
        "verification",
        "按当前有效人工验证轮次最新实际提交人归属。",
    )
    return result


def linked_work_scope(rows, params, slug, user, project=None):
    """Cycle/module identity is an intersection, never a way to switch projects."""
    from plane.db.models import Cycle, Module, CycleIssue, ModuleIssue

    for parameter, model, link_model, relation in [
        ("cycle_id", Cycle, CycleIssue, "cycle"),
        ("module_id", Module, ModuleIssue, "module"),
    ]:
        if not params.get(parameter):
            continue
        visible = Project.objects.filter(
            workspace__slug=slug,
            archived_at__isnull=True,
            project_projectmember__member=user,
            project_projectmember__is_active=True,
        )
        candidates = model.objects.filter(workspace__slug=slug, project_id__in=visible.values("pk"))
        if project:
            candidates = candidates.filter(project=project)
        obj = get_object_or_404(candidates, pk=serializers.UUIDField().run_validation(params[parameter]))
        links = link_model.objects.filter(**{relation: obj, "project_id": obj.project_id}).values("issue_id")
        rows = rows.filter(project_id=obj.project_id, pk__in=links)
    return rows


def source_spec(view, data, project):
    request, params = view.request, view.request.query_params
    source, metric = data["source"], data["metric"]
    if source == "defects":
        from .statistics import statistics_queryset

        rows = statistics_queryset(project, params, request.user)
        if metric == "unclosed":
            rows = rows.exclude(status="closed")
        elif metric in {"open", "in_progress", "pending_tech", "needs_tech", "resolved", "closed"}:
            rows = rows.filter(status=metric)
        elif metric != "total":
            raise serializers.ValidationError({"metric": "请选择有效缺陷指标。"})
        return specification(
            rows, "assignee_id", "status", "defect", "按缺陷当前负责人归属；与本页日期、来源、归档及状态筛选一致。"
        )
    if source == "quality":
        choices = quality_queries(project, params)
        if metric not in choices:
            raise serializers.ValidationError({"metric": "请选择有效测试概览指标。"})
        return choices[metric]
    if source == "period":
        from .project_report import PeriodInput, period_querysets

        options = PeriodInput(data=params)
        options.is_valid(raise_exception=True)
        scope = period_querysets(project, options.validated_data)
        queries = {**scope["detail_queries"], **scope["current_queries"]}
        if metric == "all_test_executions":
            parts = []
            for key, kind in [("test_executions", "execution"), ("verification_case_executions", "case_execution")]:
                rows = queries[key]
                if options.validated_data.get("result"):
                    rows = rows.filter(result=options.validated_data["result"])
                parts.append(specification(rows, "created_by_id", "result", kind, "区间实际执行记录，排除旧执行快照副本。"))
            return {"parts": parts}
        if metric not in queries:
            raise serializers.ValidationError({"metric": "请选择有效工作报表指标。"})
        query = queries[metric]
        if metric in {"test_executions", "verification_case_executions", "manual_executions"}:
            if options.validated_data.get("result"):
                query = query.filter(result=options.validated_data["result"])
            execution_kind = {
                "test_executions": "execution",
                "verification_case_executions": "case_execution",
                "manual_executions": "manual_execution",
            }[metric]
            return specification(
                query,
                "created_by_id",
                "result",
                execution_kind,
                "区间真实执行记录按实际执行人归属，保留每次历史结果。",
            )
        if metric.startswith("work") or metric == "current_work":
            return specification(
                query,
                "assignees__id",
                "state__group",
                "work",
                "按当前负责人归属；每个协作人计一次，独立任务总数去重；区间活动不追溯历史负责人。",
                True,
            )
        if metric in {"plans_confirmed", "current_plans"}:
            return specification(
                query, "assignee_id", "status", "plan", "按计划当前负责人归属；区间按原审批事件筛选，不等同历史审批人。"
            )
        return specification(
            query,
            "assignee_id",
            "status",
            "defect",
            "按缺陷当前负责人归属；区间活动复用原事件及归档范围，不追溯事件发生时负责人。",
        )
    if source == "work_items":
        from plane.app.views.view.base import workspace_issue_queryset

        if metric != "total_work_items":
            raise serializers.ValidationError({"metric": "请选择有效工作项指标。"})
        rows = workspace_issue_queryset(request, view.scope_slug)
        if project:
            rows = rows.filter(project=project)
        rows = linked_work_scope(rows, params, view.scope_slug, request.user, project)
        return specification(
            rows,
            "assignees__id",
            "state__group",
            "work",
            "与当前工作项列表的权限、rich_filters及筛选完全同源；每位协作负责人计一次，独立任务总数去重。",
            True,
        )
    filters = get_analytics_filters(
        view.scope_slug, request.user, "analytics", params.get("date_filter"), params.get("project_ids")
    )
    portfolio_metrics = {
        "total_defects": (
            Defect.objects.filter(archived_at__isnull=True),
            "assignee_id",
            "status",
            "defect",
            "按当前缺陷负责人归属。",
        ),
        "total_test_plans": (
            TestPlan.objects.filter(archived_at__isnull=True).exclude(status="cancelled"),
            "assignee_id",
            "status",
            "plan",
            "按当前计划负责人归属，排除归档和取消。",
        ),
        "total_test_executions": (
            TestExecution.objects.all(),
            "created_by_id",
            "result",
            "execution",
            "历史用例执行按每次实际执行人归属。",
        ),
        "total_case_round_executions": (
            DefectVerificationCaseExecution.objects.filter(source_execution__isnull=True),
            "created_by_id",
            "result",
            "case_execution",
            "缺陷回归用例执行按实际操作人归属；管理员代执行保留管理员为实际操作人。",
        ),
        "total_manual_executions": (
            DefectVerificationResult.objects.all(),
            "created_by_id",
            "result",
            "manual_execution",
            "历史人工实测按每次实际提交人归属。",
        ),
    }
    if metric in portfolio_metrics:
        if any(params.get(key) for key in ["cycle_id", "module_id", "cycle", "module", "epic"]):
            raise serializers.ValidationError({"metric": "此指标按项目统计，不适用周期、模块或史诗筛选。"})
        rows, owner, status, kind, basis = portfolio_metrics[metric]
        visible = Project.objects.filter(**filters["project_filters"])
        if project:
            visible = visible.filter(pk=project.pk)
        rows = rows.filter(project_id__in=visible.values("pk"))
        if params.get("status"):
            rows = rows.filter(**{status: params["status"]})
        if filters["analytics_date_range"]:
            window = filters["analytics_date_range"]["current"]
            rows = rows.filter(created_at__gte=window["gte"], created_at__lte=window["lte"])
        return specification(rows, owner, status, kind, basis + "采用可见项目与日期范围。")
    resource_metrics = {
        "total_projects": ("project_lead_id", "project", "项目当前负责人，不用创建人替代。"),
        "total_cycles": ("owned_by_id", "cycle", "周期当前拥有者。"),
        "total_modules": ("lead_id", "module", "模块当前负责人。"),
        "total_pages": ("page__owned_by_id", "page", "可见页面当前拥有者。"),
        "total_views": ("owned_by_id", "view", "可见视图当前拥有者。"),
        "total_users": ("member_id", "member", "成员身份数量按成员本人分组，不是事项负责人。"),
        "total_admins": ("member_id", "member", "工作区管理员身份按成员本人分组，不是事项负责人。"),
        "total_members": ("member_id", "member", "工作区成员身份按成员本人分组，不是事项负责人。"),
        "total_guests": ("member_id", "member", "工作区访客身份按成员本人分组，不是事项负责人。"),
    }
    if metric in resource_metrics:
        from plane.app.views.analytic.advance import AdvanceAnalyticsBaseView
        from plane.app.views.analytic.drilldown import overview_queries

        dummy = SimpleNamespace(filters=filters, request=request, _workspace_slug=view.scope_slug)
        dummy.member_queryset = lambda: AdvanceAnalyticsBaseView.member_queryset(dummy)
        rows = overview_queries(dummy)[metric]
        if project:
            if metric == "total_projects":
                rows = rows.filter(pk=project.pk)
            elif metric in {"total_users", "total_admins", "total_members", "total_guests"}:
                rows = rows.filter(
                    member_id__in=ProjectMember.objects.filter(project=project, is_active=True).values("member_id")
                )
            else:
                rows = rows.filter(project=project)
        if filters["analytics_date_range"]:
            window = filters["analytics_date_range"]["current"]
            rows = rows.filter(created_at__gte=window["gte"], created_at__lte=window["lte"])
        owner, kind, basis = resource_metrics[metric]
        rows = rows.annotate(
            resource_status=Value("member" if kind == "member" else "active", output_field=CharField())
        )
        return specification(
            rows,
            owner,
            "role" if kind == "member" else "status" if kind == "module" else "resource_status",
            kind,
            basis,
        )
    if project:
        from plane.app.views.analytic.project_analytics import ProjectAdvanceAnalyticsBaseView

        dummy = SimpleNamespace(filters=filters, _workspace_slug=view.scope_slug, request=request)
        rows = ProjectAdvanceAnalyticsBaseView.selected_work_items(
            dummy, project.id, params.get("cycle_id"), params.get("module_id")
        )
    else:
        from plane.app.views.analytic.drilldown import analytics_work_queryset

        dummy = SimpleNamespace(filters=filters, request=request)
        rows = analytics_work_queryset(dummy)
    states = {
        "started_work_items": "started",
        "backlog_work_items": "backlog",
        "un_started_work_items": "unstarted",
        "completed_work_items": "completed",
        "cancelled_work_items": "cancelled",
    }
    if metric == "total_intake":
        from plane.app.views.analytic.drilldown import analytics_work_queryset

        rows = analytics_work_queryset(
            SimpleNamespace(filters=filters, request=request),
            Issue.objects.filter(**filters["base_filters"], issue_intake__status__in=[-2, -1, 0, 1, 2]),
        )
        if project:
            rows = rows.filter(project=project)
    elif metric in states:
        rows = rows.filter(state__group=states[metric])
    elif metric != "total_work_items":
        raise serializers.ValidationError({"metric": "请选择有效工作项分析指标。"})
    if filters["analytics_date_range"]:
        window = filters["analytics_date_range"]["current"]
        rows = rows.filter(created_at__gte=window["gte"], created_at__lte=window["lte"])
    return specification(
        rows,
        "assignees__id",
        "state__group",
        "work",
        "按当前负责人协作归属；每人计一次，独立任务总量去重，与本页可见项目及日期范围一致。",
        True,
    )


def detail_row(row, kind, slug):
    title = getattr(row, "name", getattr(row, "title", ""))
    project_id = row.pk if kind == "project" else None if kind == "member" else row.project_id
    project_name = row.name if kind == "project" else "工作区成员" if kind == "member" else row.project.name
    if kind == "member":
        title = row.member.display_name or row.member.username
        path = f"/{slug}/profile/{row.member_id}"
    elif kind == "project":
        path = "issues/"
    elif kind == "cycle":
        path = f"cycles/{row.pk}/"
    elif kind == "module":
        path = f"modules/{row.pk}/"
    elif kind == "page":
        title = row.page.name
        path = f"pages/{row.page_id}/"
    elif kind == "view":
        path = f"views/{row.pk}/"
    elif kind == "work":
        path = f"issues/{row.pk}/"
    elif kind == "plan":
        path = f"quality?tab=plans&plan={row.pk}"
    elif kind == "case":
        path = f"quality?tab=cases&case={row.pk}"
    elif kind in {"item", "execution"}:
        item = row if kind == "item" else row.item
        title = item.revision.title
        path = f"quality?tab=plans&plan={item.plan_id}"
    elif kind == "verification_case":
        title = row.title
        path = f"defects?defect={row.verification.defect_id}"
    elif kind == "case_execution":
        title = row.item.title
        path = f"defects?defect={row.item.verification.defect_id}"
    elif kind in {"verification", "manual_execution"}:
        verification = row if kind == "verification" else row.verification
        title = verification.defect.title
        path = f"defects?defect={verification.defect_id}"
    else:
        path = f"defects?defect={row.pk}"
    return {
        "id": str(row.pk),
        "title": title,
        "project_id": str(project_id) if project_id else None,
        "project_name": project_name,
        "status": row.stat_status or "none",
        "kind": kind,
        "url": path if kind == "member" else f"/{slug}/projects/{project_id}/{path}",
    }


def mixed_owner_response(spec, data, slug, project):
    parts = spec["parts"]
    page = data["page"]
    per_page = data.get("per_page", 20 if "owner_id" in data else 10)
    offset = (page - 1) * per_page
    total = sum(part["query"].order_by().values("pk").distinct().count() for part in parts)
    common = {"page": page, "per_page": per_page, "total": total, "collaborative": False,
              "ownership_basis": parts[0]["ownership_basis"]}
    statuses = {}
    records = []
    record_count = 0
    for part in parts:
        rows = part["query"].order_by().distinct().annotate(
            stat_owner=F(part["owner"]),
            stat_status=Coalesce(Cast(F(part["status"]), CharField()), Value("none"), output_field=CharField()),
        )
        if data.get("owner_status"):
            rows = rows.filter(stat_status=data["owner_status"])
        if "owner_id" in data:
            rows = rows.filter(stat_owner=None if data["owner_id"] == "unassigned" else data["owner_id"])
            record_count += rows.count()
            relations = {"item": ["revision", "plan"], "execution": ["item__revision", "item__plan"],
                         "verification_case": ["verification__defect"], "case_execution": ["item__verification__defect"]}
            rows = rows.select_related("project", *relations.get(part["kind"], []))
            for row in rows.order_by("-created_at", "pk")[:offset + per_page]:
                records.append((row.created_at, str(row.pk), detail_row(row, part["kind"], slug)))
        else:
            for row in rows.values("stat_owner", "stat_status").annotate(count=Count("pk", distinct=True)):
                key = str(row["stat_owner"] or "unassigned")
                statuses.setdefault(key, Counter())[row["stat_status"]] += row["count"]
    if "owner_id" in data:
        records.sort(key=lambda entry: (-entry[0].timestamp(), entry[1]))
        return Response({**common, "count": record_count, "results": [entry[2] for entry in records[offset:offset + per_page]]})
    groups = sorted(statuses, key=lambda key: (-sum(statuses[key].values()), key))
    selected = groups[offset:offset + per_page]
    users = {str(user.pk): user for user in User.objects.filter(pk__in=[key for key in selected if key != "unassigned"])}
    active = set(str(value) for value in ProjectMember.objects.filter(
        project=project, member_id__in=[key for key in selected if key != "unassigned"], is_active=True,
        member__is_active=True, member__member_workspace__workspace_id=project.workspace_id,
        member__member_workspace__is_active=True,
    ).values_list("member_id", flat=True))
    results = []
    for key in selected:
        user = users.get(key)
        results.append({"owner_id": key, "name": (user.display_name or user.first_name or user.username) if user else "未指派",
                        "active": bool(user and key in active), "count": sum(statuses[key].values()),
                        "statuses": [{"status": status, "count": count} for status, count in sorted(statuses[key].items())]})
    return Response({**common, "count": len(groups), "results": results})


class OwnerStatistics(BaseAPIView):
    def get(self, request, slug=None, workspace_slug=None, project_id=None, **kwargs):
        self.scope_slug = slug or workspace_slug
        options = OwnerQuery(data=request.query_params)
        options.is_valid(raise_exception=True)
        data = options.validated_data
        admin = False
        membership = WorkspaceMember.objects.filter(
            workspace__slug=self.scope_slug, member=request.user, is_active=True
        )
        minimum = 5 if data["source"] in {"defects", "quality", "work_items"} else 15
        if not membership.filter(role__gte=minimum).exists():
            admin = is_administrator(request.user)
            if not admin:
                raise PermissionDenied("您没有当前工作区统计权限。")
        project = None
        if project_id:
            project = get_object_or_404(
                Project,
                pk=project_id,
                workspace__slug=self.scope_slug,
                archived_at__isnull=True,
                workspace__deleted_at__isnull=True,
            )
            if not ProjectMember.objects.filter(
                project=project, member=request.user, is_active=True, role__gte=minimum
            ).exists():
                if not admin and not is_administrator(request.user):
                    raise PermissionDenied("您没有当前项目统计权限。")
        elif data["source"] in {"defects", "quality", "period"}:
            raise serializers.ValidationError({"source": "此指标需要项目范围。"})
        spec = source_spec(self, data, project)
        if "parts" in spec:
            return mixed_owner_response(spec, data, self.scope_slug, project)
        if spec["kind"] == "work":
            spec["query"] = spec["query"].annotate(
                active_owner=FilteredRelation("issue_assignee", condition=Q(issue_assignee__deleted_at__isnull=True))
            )
            spec["owner"] = "active_owner__assignee_id"
        rows = (
            spec["query"]
            .order_by()
            .distinct()
            .annotate(
                stat_owner=F(spec["owner"]) if spec["owner"] else Value(None, output_field=UUIDField()),
                stat_status=Coalesce(Cast(F(spec["status"]), CharField()), Value("none"), output_field=CharField()),
            )
        )
        total = spec["query"].order_by().values("pk").distinct().count()
        if data.get("owner_status"):
            rows = rows.filter(stat_status=data["owner_status"])
        page = data["page"]
        per_page = data.get("per_page", 20 if "owner_id" in data else 10)
        offset = (page - 1) * per_page
        common = {
            "page": page,
            "per_page": per_page,
            "total": total,
            "ownership_basis": spec["ownership_basis"],
            "collaborative": spec["collaborative"],
        }
        if "owner_id" in data:
            rows = rows.filter(stat_owner=None if data["owner_id"] == "unassigned" else data["owner_id"])
            if spec["kind"] not in {"project", "member"}:
                rows = rows.select_related("project")
            if spec["kind"] in {"member", "page"}:
                rows = rows.select_related("member" if spec["kind"] == "member" else "page")
            if spec["kind"] in {"item", "execution"}:
                rows = rows.select_related("revision" if spec["kind"] == "item" else "item__revision")
            if spec["kind"] == "verification_case":
                rows = rows.select_related("verification__defect")
            if spec["kind"] == "case_execution":
                rows = rows.select_related("item__verification__defect")
            if spec["kind"] in {"verification", "manual_execution"}:
                rows = rows.select_related("defect" if spec["kind"] == "verification" else "verification__defect")
            return Response(
                {
                    **common,
                    "count": rows.count(),
                    "results": [
                        detail_row(row, spec["kind"], self.scope_slug)
                        for row in rows.order_by("-created_at", "pk")[offset : offset + per_page]
                    ],
                }
            )
        totals = rows.order_by().values("stat_owner").annotate(count=Count("pk", distinct=True))
        owner_count = totals.count()
        selected = list(totals.order_by("-count", "stat_owner")[offset : offset + per_page])
        owner_ids = [row["stat_owner"] for row in selected if row["stat_owner"]]
        condition = Q(stat_owner__in=owner_ids)
        if any(row["stat_owner"] is None for row in selected):
            condition |= Q(stat_owner__isnull=True)
        statuses = {}
        for row in (
            rows.filter(condition)
            .order_by()
            .values("stat_owner", "stat_status")
            .annotate(count=Count("pk", distinct=True))
        ):
            statuses.setdefault(str(row["stat_owner"] or "unassigned"), []).append(
                {"status": row["stat_status"], "count": row["count"]}
            )
        users = {str(user.pk): user for user in User.objects.filter(pk__in=owner_ids)}
        active_ids = (
            set(str(pk) for pk in owner_ids)
            if spec["kind"] == "member"
            else set(
                str(pk)
                for pk in ProjectMember.objects.filter(
                    project_id__in=spec["query"].values("pk" if spec["kind"] == "project" else "project_id"),
                    member_id__in=owner_ids,
                    is_active=True,
                    member__is_active=True,
                    member__member_workspace__workspace__slug=self.scope_slug,
                    member__member_workspace__is_active=True,
                ).values_list("member_id", flat=True)
            )
        )
        groups = []
        for row in selected:
            key = str(row["stat_owner"] or "unassigned")
            user = users.get(key)
            groups.append(
                {
                    "owner_id": key,
                    "count": row["count"],
                    "name": (user.display_name or user.first_name or user.username or "成员") if user else "未指派",
                    "active": bool(user and user.is_active and key in active_ids),
                    "statuses": sorted(statuses.get(key, []), key=lambda value: value["status"]),
                }
            )
        return Response({**common, "count": owner_count, "results": groups})
