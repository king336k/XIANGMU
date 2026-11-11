# SPDX-License-Identifier: AGPL-3.0-only
"""Transactional in-app notifications; no mail or third-party delivery."""

from plane.db.models import Notification, ProjectMember
from .models import BusinessRole
from .permissions import strict
from django.db.models import Q


def managers(project):
    qs = ProjectMember.objects.filter(project=project, is_active=True)
    if strict(project.id):
        qs = qs.filter(
            member_id__in=BusinessRole.objects.filter(project=project).filter(
                Q(role__in=["PLATFORM_ADMIN", "PROJECT_MANAGER"])
                | Q(additional_roles__contains=["PLATFORM_ADMIN"])
                | Q(additional_roles__contains=["PROJECT_MANAGER"])
            ).values("user_id")
        )
    else:
        qs = qs.filter(role=20)
    return qs.values_list("member_id", flat=True)


def notify(project, actor, receivers, entity_id, title, path):
    allowed = (
        ProjectMember.objects.filter(
            project=project,
            is_active=True,
            role__gte=15,
            member_id__in={value for value in receivers if value},
            member__member_workspace__workspace=project.workspace,
            member__member_workspace__is_active=True,
        )
        .exclude(member=actor)
        .values_list("member_id", flat=True)
        .distinct()
    )
    url = f"/{project.workspace.slug}/projects/{project.id}/{path}"
    for receiver in allowed:
        Notification.objects.create(
            workspace=project.workspace,
            project=project,
            receiver_id=receiver,
            triggered_by=actor,
            sender="quality",
            title=title,
            entity_name="quality",
            entity_identifier=entity_id,
            data={"quality": {"title": title, "url": url}, "issue_activity": {"field": "quality", "verb": "updated"}},
            message={"text": title},
        )


def plan_notice(plan, action, actor):
    names = {
        "assign": "测试计划已分派给你",
        "submit": "测试结果等待你确认",
        "return": "测试结果被退回，请补充复测",
        "approve": "测试结果已由经理确认",
        "cancel": "测试计划已取消",
    }
    if action not in names:
        return
    receivers = managers(plan.project) if action == "submit" else [plan.assignee_id, plan.created_by_id]
    notify(
        plan.project, actor, receivers, plan.id, f"{names[action]}：{plan.name}", f"quality?tab=plans&plan={plan.id}"
    )


def defect_notice(defect, actor, title, receivers=()):
    targets = {
        defect.assignee_id,
        defect.created_by_id,
        *receivers,
        *defect.collaborators.values_list("user_id", flat=True),
    }
    notify(defect.project, actor, targets, defect.id, f"{title}：{defect.title}", f"defects?defect={defect.id}")


def serialize_with_current_status(notifications, request):
    """Batch current states for the visible notifications; historical messages stay unchanged."""
    from urllib.parse import urlsplit, parse_qs
    from plane.app.serializers import NotificationSerializer
    from plane.db.models import Issue
    from .models import Defect, TestPlan, Requirement

    rows = list(notifications)
    data = NotificationSerializer(rows, many=True).data
    projects = set(
        ProjectMember.objects.filter(
            project_id__in={row.project_id for row in rows},
            member=request.user,
            is_active=True,
            role__in=[5, 15, 20],
            project__archived_at__isnull=True,
            member__member_workspace__workspace_id__in={row.workspace_id for row in rows},
            member__member_workspace__is_active=True,
        ).values_list("project_id", flat=True)
    )
    ids = {row.entity_identifier for row in rows if row.project_id in projects and row.entity_identifier}
    defects = {row.id: row for row in Defect.objects.filter(id__in=ids, project_id__in=projects)}
    plans = {row.id: row for row in TestPlan.objects.filter(id__in=ids, project_id__in=projects)}
    issues = {row.id: row for row in Issue.objects.filter(id__in=ids, project_id__in=projects).select_related("state")}
    requirements = {row.issue_id: row for row in Requirement.objects.filter(issue_id__in=ids, project_id__in=projects)}
    labels = {
        "defect": {"open": "待处理", "in_progress": "处理中", "resolved": "已修复，待回归", "closed": "已关闭"},
        "plan": {
            "pending": "待分派",
            "ready": "待认领",
            "running": "测试中",
            "paused": "已暂停",
            "review": "待确认测试结果",
            "completed": "测试结果已确认",
            "returned": "已退回，待复测",
            "cancelled": "已取消",
        },
        "requirement": {
            "draft": "待完善",
            "review": "待审核",
            "approved": "已确认",
            "in_progress": "实现中",
            "completed": "验收完成",
            "cancelled": "已取消",
            "archived": "已归档",
        },
    }
    for row, item in zip(rows, data):
        record = None
        if row.project_id not in projects:
            continue
        if row.entity_name == "quality":
            url = (row.data or {}).get("quality", {}).get("url", "")
            query = parse_qs(urlsplit(url).query)
            kind = (
                "defect"
                if "defect" in query
                else "plan"
                if "plan" in query
                else "requirement"
                if "requirement" in query
                else "issue"
                if "/issues/" in urlsplit(url).path
                else None
            )
            obj = {"defect": defects, "plan": plans, "requirement": requirements}.get(kind, {}).get(
                row.entity_identifier
            )
            if obj and obj.project_id == row.project_id:
                record = {
                    "kind": kind,
                    "status": obj.status,
                    "label": "已归档"
                    if getattr(obj, "archived_at", None)
                    else labels[kind].get(obj.status, "状态已更新"),
                    "available": True,
                }
        if row.entity_name == "issue" or (row.entity_name == "quality" and kind == "issue"):
            issue = issues.get(row.entity_identifier)
            if issue and issue.project_id == row.project_id:
                requirement = requirements.get(issue.id)
                defaults = {
                    "Backlog": "待排期",
                    "Todo": "待开始",
                    "In Progress": "进行中",
                    "Done": "已完成",
                    "Cancelled": "已取消",
                }
                record = {
                    "kind": "requirement" if requirement else "task",
                    "status": requirement.status if requirement else issue.state.group,
                    "label": labels["requirement"].get(requirement.status, "状态已更新")
                    if requirement
                    else "已归档"
                    if issue.archived_at
                    else defaults.get(issue.state.name, issue.state.name),
                    "available": True,
                }
        item["data"] = {
            **(item.get("data") or {}),
            "current_record": record
            or {"kind": "record", "status": "unavailable", "label": "记录已移除或不可访问", "available": False},
        }
    return data
