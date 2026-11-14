# SPDX-License-Identifier: AGPL-3.0-only
"""Transactional in-app notifications; no mail or third-party delivery."""

from plane.db.models import Notification, ProjectMember, User
from .permissions import strict, roles_for, is_administrator, writable_member


def managers(project):
    rows = ProjectMember.objects.filter(
        project=project, is_active=True, role__gte=15, member__is_active=True, member__is_bot=False
    ).select_related("member")
    return [
        row.member_id
        for row in rows
        if writable_member(project.id, row.member_id, project.workspace.slug)
        and (
            bool(roles_for(project.id, row.member_id) & {"PROJECT_MANAGER", "PLATFORM_ADMIN"})
            if strict(project.id)
            else row.role == 20
        )
    ]


def notify(project, actor, receivers, entity_id, title, path):
    allowed = (
        ProjectMember.objects.filter(
            project=project,
            is_active=True,
            role__gte=15,
            member_id__in={value for value in receivers if value},
            member__member_workspace__workspace=project.workspace,
            member__member_workspace__is_active=True,
            member__member_workspace__role__gte=15,
            member__is_active=True,
            member__is_bot=False,
        )
        .exclude(member=actor)
        .values_list("member_id", flat=True)
        .distinct()
    )
    allowed = set(allowed)
    wanted = {value for value in receivers if value and value != getattr(actor, "id", None)}
    for user in User.objects.filter(pk__in=wanted - allowed, is_active=True, is_bot=False):
        if is_administrator(user):
            allowed.add(user.pk)
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
        "claim": "测试已认领",
        "submit": "测试结果等待你确认",
        "return": "测试结果被退回，请补充复测",
        "approve": "测试结果已由经理确认",
        "cancel": "测试计划已取消",
        "update": "本轮测试内容已更新",
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
    from .reference_names import readable_references

    rows = list(notifications)
    reference_context = {}
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
    if any(row.entity_name == "quality" and row.project_id not in projects for row in rows) and is_administrator(
        request.user
    ):
        projects.update(row.project_id for row in rows if row.entity_name == "quality")
    ids = {row.entity_identifier for row in rows if row.project_id in projects and row.entity_identifier}
    defects = {
        row.id: row
        for row in Defect.objects.filter(id__in=ids, project_id__in=projects).select_related("module", "assignee")
    }
    plans = {
        row.id: row
        for row in TestPlan.objects.filter(id__in=ids, project_id__in=projects)
        .select_related("defect_verification__defect", "assignee")
    }
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
                if kind == "plan" and getattr(obj, "defect_verification", None) and not obj.archived_at:
                    from .defect_verification import execution_state
                    state = execution_state(obj.defect_verification)
                    record.update(
                        status=state,
                        label={
                            "waiting_repair": "待修复", "needs_arrangement": "待重新安排", "pending": "待测试",
                            "running": "测试中", "tested": "已测试，待提交", "review": "待验收",
                            "accepted": "已验收", "returned_repair": "退回修复", "returned_test": "退回补测",
                            "superseded": "已调整", "reopened": "已重新打开",
                        }.get(state, "状态已更新"),
                        assignee_name=(obj.assignee.display_name or obj.assignee.username)
                        if obj.assignee_id else "待认领",
                    )
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
        defect_context = None
        if record and record.get("kind") == "defect":
            defect = defects.get(row.entity_identifier)
            if defect:
                defect_context = {
                    "module": {"key": defect.module_id, "name": defect.module.name} if defect.module_id else None,
                    "assignee_name": (defect.assignee.display_name or defect.assignee.username)
                    if defect.assignee_id
                    else "",
                    "origin": defect.assignment_origin,
                    "reason": readable_references(
                        defect.assignment_reason, defect.project_id, defect.id, reference_context
                    ),
                    "url": (row.data or {}).get("quality", {}).get("url", ""),
                }
        item["data"] = {
            **(item.get("data") or {}),
            **({"defect_context": defect_context} if defect_context else {}),
            "current_record": record
            or {"kind": "record", "status": "unavailable", "label": "记录已移除或不可访问", "available": False},
        }
    return data
