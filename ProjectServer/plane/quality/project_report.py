# SPDX-License-Identifier: AGPL-3.0-only
"""Period activity and current responsibility are deliberately separate projections."""

from collections import Counter
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.db.models import Q, Count, Exists, OuterRef
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from plane.db.models import Issue, IssueActivity, IssueAssignee, ProjectMember, WorkspaceMember, State
from .models import (
    BusinessRole,
    Defect,
    DefectEvent,
    TestPlan,
    TestExecution,
    PlanEvent,
    PlanItem,
    Requirement,
    DefectVerificationResult,
)
from .views import QualityView, current_plans
from .permissions import ROLE_NAMES


class PeriodInput(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    timezone = serializers.CharField(default="Asia/Shanghai")

    def validate_timezone(self, value):
        return "Asia/Shanghai"

    detail = serializers.ChoiceField(
        choices=[
            "work_created",
            "work_completed",
            "defects_created",
            "defects_closed",
            "defects_reopened",
            "test_executions",
            "manual_executions",
            "plans_confirmed",
            "workload",
            "current_work",
            "current_plans",
            "current_defects",
        ],
        required=False,
    )
    page = serializers.IntegerField(min_value=1, default=1)
    per_page = serializers.IntegerField(min_value=1, max_value=100, default=20)
    resource = serializers.ChoiceField(choices=["work", "plans", "defects"], required=False)
    status = serializers.CharField(max_length=30, required=False)
    assignee_id = serializers.CharField(max_length=50, required=False)
    result = serializers.ChoiceField(choices=["passed", "failed", "blocked", "inconclusive", "skipped"], required=False)

    def validate(self, attrs):
        if attrs["start"] > attrs["end"]:
            raise serializers.ValidationError({"end": "结束日期不能早于开始日期。"})
        if (attrs["end"] - attrs["start"]).days > 365:
            raise serializers.ValidationError({"end": "单次最多统计366天，请缩小时间范围。"})
        return attrs


def report_access(view):
    if (
        not ProjectMember.objects.filter(
            project_id=view.project_id, member=view.request.user, is_active=True, role__gte=15
        ).exists()
        or not WorkspaceMember.objects.filter(
            workspace__slug=view.workspace_slug, member=view.request.user, is_active=True, role__gte=15
        ).exists()
    ):
        raise PermissionDenied("项目工作报表仅对当前项目的有效成员开放。")


def grouped(qs, field):
    return {
        str(row[field] or "unassigned"): row["count"] for row in qs.order_by().values(field).annotate(count=Count("pk"))
    }


def period_querysets(project, data):
    zone = ZoneInfo(data["timezone"])
    start = datetime.combine(data["start"], time.min, tzinfo=zone)
    end = datetime.combine(data["end"] + timedelta(days=1), time.min, tzinfo=zone)
    window = {"created_at__gte": start, "created_at__lt": end}
    work = Issue.issue_objects.filter(project=project)
    all_defects = Defect.objects.filter(project=project)
    defects = all_defects.filter(archived_at__isnull=True)
    plans = TestPlan.objects.filter(project=project)
    terminal_requirements = Requirement.objects.filter(
        project=project, status__in=["completed", "cancelled", "archived"]
    ).values("issue_id")
    current_work = work.exclude(state__group__in=["completed", "cancelled"]).exclude(pk__in=terminal_requirements)
    active_members = ProjectMember.objects.filter(
        project=project,
        is_active=True,
        member__is_active=True,
        member__is_bot=False,
        member__member_workspace__workspace=project.workspace,
        member__member_workspace__is_active=True,
    ).distinct()
    pending_items = (
        PlanItem.objects.filter(project=project)
        .annotate(
            has_execution=Exists(
                TestExecution.objects.filter(item_id=OuterRef("pk")).filter(
                    Q(item__plan__managed=False, item__plan__defect_verification__isnull=True)
                    | Q(round_no=OuterRef("plan__round_no"))
                )
            )
        )
        .filter(has_execution=False)
    )
    unfinished_plans = (
        current_plans(project)
        .exclude(status__in=["completed", "cancelled", "failed"])
        .filter(
            Q(managed=True) & ~Q(status__in=["completed", "cancelled", "failed"])
            | Q(defect_verification__status__in=["testing", "review"])
            | Q(managed=False) & (Q(pk__in=pending_items.values("plan_id")) | Q(items__isnull=True))
        )
        .distinct()
    )
    executions = TestExecution.objects.filter(project=project)
    # Activities are append-only. Fallback completion timestamps cover direct native writes without activities.
    completed_states = State.objects.filter(project=project, group="completed").values("id")
    completed_activity = IssueActivity.objects.filter(
        project=project,
        issue_id__in=work.values("id"),
        field="state",
        new_identifier__in=completed_states,
        **window,
    ).exclude(old_identifier__in=completed_states)
    completed_work = work.filter(
        Q(pk__in=completed_activity.values("issue_id")) | Q(completed_at__gte=start, completed_at__lt=end)
    )
    closure = DefectEvent.objects.filter(
        project=project, defect_id__in=all_defects.values("id"), status="closed", **window
    ).exclude(previous_status="closed")
    reopened = DefectEvent.objects.filter(
        project=project, defect_id__in=all_defects.values("id"), previous_status="closed", **window
    ).exclude(status="closed")
    confirmed = PlanEvent.objects.filter(
        project=project, plan_id__in=plans.values("id"), action="approve", status="completed", **window
    )
    period_executions = executions.filter(**window)
    manual_executions = DefectVerificationResult.objects.filter(project=project, **window)
    confirmed_plans = plans.filter(
        Q(pk__in=confirmed.values("plan_id"))
        | Q(
            defect_verification__workflow_events__action="accept",
            defect_verification__workflow_events__created_at__gte=start,
            defect_verification__workflow_events__created_at__lt=end,
        )
    ).distinct()
    detail_queries = {
        "work_created": work.filter(**window),
        "work_completed": completed_work,
        "defects_created": all_defects.filter(**window),
        "defects_closed": all_defects.filter(pk__in=closure.values("defect_id")),
        "defects_reopened": all_defects.filter(pk__in=reopened.values("defect_id")),
        "test_executions": period_executions,
        "manual_executions": manual_executions,
        "plans_confirmed": confirmed_plans,
    }
    current_queries = {
        "current_work": current_work,
        "current_plans": unfinished_plans,
        "current_defects": defects.exclude(status="closed"),
    }
    return {
        "zone": zone,
        "active_members": active_members,
        "current_work": current_work,
        "unfinished_plans": unfinished_plans,
        "defects": defects,
        "period_executions": period_executions,
        "manual_executions": manual_executions,
        "closure": closure,
        "detail_queries": detail_queries,
        "current_queries": current_queries,
    }


class ProjectPeriodReport(QualityView):
    def get(self, request, **kwargs):
        report_access(self)
        options = PeriodInput(data=request.query_params)
        options.is_valid(raise_exception=True)
        data = options.validated_data
        project = self.project()
        scope = period_querysets(project, data)
        zone = scope["zone"]
        active_members = scope["active_members"]
        current_work = scope["current_work"]
        unfinished_plans = scope["unfinished_plans"]
        defects = scope["defects"]
        period_executions = scope["period_executions"]
        manual_executions = scope["manual_executions"]
        closure = scope["closure"]
        detail_queries = scope["detail_queries"]
        current_queries = scope["current_queries"]
        if data.get("detail"):
            kind = data["detail"]
            if kind == "workload":
                resource = data.get("resource")
                status = data.get("status")
                statuses = {
                    "work": {"backlog", "unstarted", "started"},
                    "plans": {"pending", "ready", "running", "paused", "review", "returned", "unexecuted"},
                    "defects": {"open", "in_progress", "resolved"},
                }
                if resource not in statuses or status not in statuses[resource] or not data.get("assignee_id"):
                    raise serializers.ValidationError({"detail": "请选择人员、记录类型和有效状态。"})
                qs = {"work": current_work, "plans": unfinished_plans, "defects": defects}[resource]
                qs = (
                    qs.filter(Q(state__group="backlog") | Q(state__isnull=True))
                    if resource == "work" and status == "backlog"
                    else (
                        qs.filter(managed=False, defect_verification__isnull=True)
                        if resource == "plans" and status == "unexecuted"
                        else (
                            qs.filter(Q(managed=True) | Q(defect_verification__isnull=False), status=status)
                            if resource == "plans"
                            else qs.filter(**{"state__group" if resource == "work" else "status": status})
                        )
                    )
                )
                assignee = data["assignee_id"]
                field = "assignees" if resource == "work" else "assignee"
                if assignee == "unassigned":
                    qs = qs.filter(**{field + "__isnull": True})
                elif assignee == "outside":
                    active = active_members.values("member_id")
                    if resource == "work":
                        outside = (
                            IssueAssignee.objects.filter(project=project)
                            .exclude(assignee_id__in=active)
                            .values("assignee_id")
                        )
                        qs = qs.filter(assignees__in=outside)
                    else:
                        qs = qs.filter(assignee__isnull=False).exclude(assignee_id__in=active)
                else:
                    qs = qs.filter(**{field: serializers.UUIDField().run_validation(assignee)})
                kind = {"work": "work_current", "plans": "plans_confirmed", "defects": "defects_current"}[resource]
                qs = qs.distinct()
            else:
                qs = {**detail_queries, **current_queries}[kind]
                if kind in {"test_executions", "manual_executions"} and data.get("result"):
                    qs = qs.filter(result=data["result"])
                kind = {
                    "current_work": "work_current",
                    "current_plans": "plans_confirmed",
                    "current_defects": "defects_current",
                }.get(kind, kind)
            qs = qs.order_by("-created_at", "id")
            offset = (data["page"] - 1) * data["per_page"]
            if kind.startswith("work"):
                records = [
                    {"id": str(row.id), "title": row.name, "path": f"issues/{row.id}/", "kind": "工作项"}
                    for row in qs[offset : offset + data["per_page"]]
                ]
            elif kind == "test_executions":
                records = [
                    {
                        "id": str(row.id),
                        "title": row.item.revision.title,
                        "result": row.result,
                        "path": f"quality?tab=plans&plan={row.item.plan_id}",
                        "kind": "测试执行",
                    }
                    for row in qs.select_related("item__revision")[offset : offset + data["per_page"]]
                ]
            elif kind == "manual_executions":
                records = [
                    {
                        "id": str(row.id),
                        "title": row.verification.defect.title,
                        "result": row.result,
                        "path": f"defects?defect={row.verification.defect_id}",
                        "kind": "人工实测",
                    }
                    for row in qs.select_related("verification__defect")[offset : offset + data["per_page"]]
                ]
            elif kind == "plans_confirmed":
                records = [
                    {
                        "id": str(row.id),
                        "title": row.name,
                        "path": f"quality?tab=plans&plan={row.id}",
                        "kind": "测试计划",
                    }
                    for row in qs[offset : offset + data["per_page"]]
                ]
            else:
                records = [
                    {
                        "id": str(row.id),
                        "title": row.title,
                        "path": f"defects?defect={row.id}",
                        "kind": "缺陷",
                    }
                    for row in qs[offset : offset + data["per_page"]]
                ]
            return Response(
                {"count": qs.count(), "results": records, "page": data["page"], "per_page": data["per_page"]}
            )
        activity = {key: query.count() for key, query in detail_queries.items()}
        activity["test_cases_executed"] = period_executions.values("item__case_id").distinct().count()
        members = active_members.select_related("member")
        roles = dict(BusinessRole.objects.filter(project=project).values_list("user_id", "role"))
        by_user = {
            str(member.member_id): {
                "user_id": str(member.member_id),
                "name": member.member.display_name or member.member.first_name or "项目成员",
                "role": ROLE_NAMES.get(roles.get(member.member_id), "项目成员"),
                "work": {},
                "plans": {},
                "defects": {},
                "period_executions": 0,
            }
            for member in members
        }
        unassigned = {
            "user_id": "unassigned",
            "name": "未指派",
            "role": "",
            "work": {},
            "plans": {},
            "defects": {},
            "period_executions": 0,
        }
        previous = {
            "user_id": "outside",
            "name": "已停用或离开项目的负责人",
            "role": "",
            "work": {},
            "plans": {},
            "defects": {},
            "period_executions": 0,
        }

        def add(user_id, kind, status, count=1):
            row = unassigned if not user_id else by_user.get(str(user_id), previous)
            row[kind][status or "backlog"] = row[kind].get(status or "backlog", 0) + count

        outside_work_seen = set()
        for row in IssueAssignee.objects.filter(project=project, issue_id__in=current_work.values("id")).values(
            "assignee_id", "issue_id", "issue__state__group"
        ):
            # Active users each own a load; the combined former-owner bucket drills to distinct issues.
            if str(row["assignee_id"]) not in by_user:
                if row["issue_id"] in outside_work_seen:
                    continue
                outside_work_seen.add(row["issue_id"])
            add(row["assignee_id"], "work", row["issue__state__group"])
        for row in current_work.filter(assignees__isnull=True).values("state__group").annotate(count=Count("pk")):
            add(None, "work", row["state__group"], row["count"])
        for key, qs in [
            ("plans", unfinished_plans),
            ("defects", defects.exclude(status="closed")),
        ]:
            for row in (
                qs.order_by()
                .values("assignee_id", "status", *(["managed", "defect_verification"] if key == "plans" else []))
                .annotate(count=Count("pk"))
            ):
                status = (
                    "unexecuted"
                    if key == "plans" and not row["managed"] and not row["defect_verification"]
                    else row["status"]
                )
                add(row["assignee_id"], key, status, row["count"])
        for user, count in grouped(period_executions, "created_by_id").items():
            (by_user.get(user, unassigned if user == "unassigned" else previous))["period_executions"] += count
        daily = {}
        for kind, qs, field in [
            ("work_created", detail_queries["work_created"], "created_at"),
            ("defects_created", detail_queries["defects_created"], "created_at"),
            ("test_executions", period_executions, "created_at"),
            ("manual_executions", manual_executions, "created_at"),
        ]:
            for value in qs.values_list(field, flat=True):
                key = value.astimezone(zone).date().isoformat()
                daily.setdefault(key, Counter())[kind] += 1
        # Count distinct defects per day while period totals remain distinct over the complete interval.
        seen = set()
        for defect_id, value in closure.values_list("defect_id", "created_at"):
            key = value.astimezone(zone).date().isoformat()
            if (key, defect_id) not in seen:
                daily.setdefault(key, Counter())["defects_closed"] += 1
                seen.add((key, defect_id))
        trend = [
            {
                "date": (data["start"] + timedelta(days=offset)).isoformat(),
                **{
                    key: daily.get((data["start"] + timedelta(days=offset)).isoformat(), {}).get(key, 0)
                    for key in [
                        "work_created",
                        "defects_created",
                        "defects_closed",
                        "test_executions",
                        "manual_executions",
                    ]
                },
            }
            for offset in range((data["end"] - data["start"]).days + 1)
        ]
        results = grouped(period_executions, "result")
        manual_results = grouped(manual_executions, "result")
        return Response(
            {
                "project": {"id": str(project.id), "name": project.name},
                "start": data["start"],
                "end": data["end"],
                "timezone": data["timezone"],
                "activity": activity,
                "current": {
                    "work_unfinished": current_work.count(),
                    "plans_unfinished": unfinished_plans.count(),
                    "defects_unclosed": defects.exclude(status="closed").count(),
                },
                "test_results": {
                    key: results.get(key, 0) for key in ["passed", "failed", "blocked", "inconclusive", "skipped"]
                },
                "manual_results": {
                    key: manual_results.get(key, 0)
                    for key in ["passed", "failed", "blocked", "inconclusive", "skipped"]
                },
                "workload": list(by_user.values())
                + (
                    [previous]
                    if any(previous[key] for key in ["work", "plans", "defects", "period_executions"])
                    else []
                ),
                "unassigned": unassigned,
                "trend": trend,
                "definitions": [
                    "区间活动使用北京时间的起止日期，包含结束日；当前待办是实时存量，不受区间限制。",
                    "测试执行保留每次追加结果，不以最终一次覆盖历史；执行用例数按不同用例去重。",
                    "人工实测独立按每次真实提交计数，不计入测试用例数；归档计划不会抹除区间历史执行。当前计划排除取消、已归档和过期缺陷验证轮次。",
                    "缺陷关闭和重开按状态变更记录按缺陷去重；未关缺陷采用当前状态，可能包含区间之前或之后创建的记录。",
                    "同一任务多人负责时，每个人的负载分别计数；人员负载之和不等于独立任务总量。",
                ],
            }
        )
