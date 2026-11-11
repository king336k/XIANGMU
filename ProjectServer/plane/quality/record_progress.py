# SPDX-License-Identifier: AGPL-3.0-only
from rest_framework import serializers
from rest_framework.response import Response
from django.db.models import Q, Value, CharField
from plane.db.models import ProjectMember, Issue
from .views import QualityView
from .models import Defect, TestPlan, ProjectVersion
from .requirements import visible_requirements
from .project_versions import flow_projection
from .history import event_page


class ProgressInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["plan", "defect", "requirement"])
    id = serializers.UUIDField()


class RecordProgress(QualityView):
    def get(self, request, **kwargs):
        options = ProgressInput(data=request.query_params)
        options.is_valid(raise_exception=True)
        data = options.validated_data
        kind = data["kind"]
        pk = data["id"]
        events = []
        dates = []
        if kind == "plan":
            row = self.obj(TestPlan, pk)
            stages = [
                ("pending", "待分派"),
                ("ready", "待认领"),
                ("running", "测试中"),
                ("review", "待确认"),
                ("completed", "结果已确认"),
            ]
            if not row.managed:
                stages = [("pending", "待执行"), ("running", "执行中"), ("completed", "已记录结果")]
            current = row.status
            labels = {
                **dict(stages),
                "paused": "已暂停",
                "returned": "待复测",
                "cancelled": "已取消",
                "failed": "回归失败，待修复",
            }
            if row.status in {"paused", "returned", "cancelled", "failed"}:
                stages.append((row.status, labels[row.status]))
            history = (
                row.workflow_events.order_by()
                .values("id", "created_at")
                .annotate(event_kind=Value("workflow", output_field=CharField()))
            )
            if not row.managed:
                from .models import TestExecution

                executions = (
                    TestExecution.objects.filter(item__plan=row)
                    .order_by()
                    .values("id", "created_at")
                    .annotate(event_kind=Value("execution", output_field=CharField()))
                )
                history = history.union(executions)
            selected, pagination = event_page(history.order_by("created_at", "id"), request)
            workflow = {
                event.id: event
                for event in row.workflow_events.filter(
                    id__in=[item["id"] for item in selected if item["event_kind"] == "workflow"]
                ).select_related("created_by")
            }
            executions = {}
            if not row.managed:
                executions = {
                    event.id: event
                    for event in TestExecution.objects.filter(
                        id__in=[item["id"] for item in selected if item["event_kind"] == "execution"]
                    ).select_related("created_by", "item__revision")
                }
            for item in selected:
                event = workflow[item["id"]] if item["event_kind"] == "workflow" else executions[item["id"]]
                execution = item["event_kind"] == "execution"
                events.append(
                    {
                        "id": str(event.id),
                        "label": f"执行用例：{event.item.revision.title}"
                        if execution
                        else labels.get(event.status, "状态已更新"),
                        "actor": event.created_by.display_name if event.created_by else "系统",
                        "date": event.created_at,
                        "note": {"passed": "通过", "failed": "失败", "blocked": "阻塞", "inconclusive": "无法判定", "skipped": "跳过"}.get(
                            event.result, event.result
                        )
                        if execution
                        else event.note,
                    }
                )
            if not row.managed:
                from .serializers import plan_summary
                from .views import plan_queryset

                summary = plan_summary(plan_queryset().get(pk=row.id))
                current = (
                    "completed"
                    if summary["total"] and summary["pending"] == 0
                    else "running"
                    if summary["executed"]
                    else "pending"
                )
            builds = [row.build]
            dates = [{"label": "创建", "date": row.created_at}, {"label": "结果确认", "date": row.reviewed_at}]
        elif kind == "defect":
            row = self.obj(Defect, pk)
            stages = [("open", "待处理"), ("in_progress", "处理中"), ("resolved", "待回归"), ("closed", "已关闭")]
            current = row.status
            selected, pagination = event_page(
                row.events.select_related("created_by").order_by("created_at", "id"), request
            )
            from .serializers import EventSerializer

            for event in selected:
                events.append(
                    {
                        "id": str(event.id),
                        "label": dict(stages).get(event.status, event.status),
                        "actor": event.created_by.display_name if event.created_by else "系统",
                        "date": event.created_at,
                        "note": EventSerializer(event).data["note"],
                    }
                )
            builds = [row.affected_build, row.fixed_build]
            dates = [{"label": "创建", "date": row.created_at}, {"label": "修复提交", "date": row.resolved_at}]
        else:
            from django.shortcuts import get_object_or_404

            row = get_object_or_404(visible_requirements(self), issue_id=pk)
            stages = [("draft", "待完善"), ("review", "待审核"), ("approved", "已确认"), ("completed", "验收完成")]
            current = row.status
            if row.status in {"cancelled", "archived"}:
                stages.append((row.status, "已取消" if row.status == "cancelled" else "已归档"))
            selected, pagination = event_page(
                row.revisions.select_related("created_by").order_by("version", "id"), request
            )
            for event in selected:
                events.append(
                    {
                        "id": str(event.id),
                        "label": f"v{event.version} · "
                        + dict(stages).get(event.snapshot.get("status", "draft"), "已更新"),
                        "actor": event.created_by.display_name if event.created_by else "成员",
                        "date": event.created_at,
                        "note": event.snapshot.get("comment", ""),
                    }
                )
            builds = [row.target_build]
            dates = [
                {"label": "计划开始", "date": row.issue.start_date},
                {"label": "目标完成", "date": row.issue.target_date},
            ]
        versions = (
            ProjectVersion.objects.filter(project_id=self.project_id)
            .filter(
                Q(version__in=[value for value in builds if value])
                | Q(flow_nodes__contains=[{"kind": kind, "object_id": str(pk)}])
            )
            .order_by("-created_at")[:20]
        )
        schedule = []
        if kind == "requirement":
            tasks = (
                Issue.issue_objects.filter(project_id=self.project_id)
                .filter(Q(pk=row.issue_id) | Q(parent_id=row.issue_id))
                .select_related("state")
            )
            if ProjectMember.objects.filter(
                project_id=self.project_id,
                member=request.user,
                is_active=True,
                role=5,
                project__guest_view_all_features=False,
            ).exists():
                tasks = tasks.filter(created_by=request.user)
            schedule = [
                {
                    "id": str(item.id),
                    "name": item.name,
                    "start": item.start_date,
                    "target": item.target_date,
                    "status": item.state.group if item.state_id else "backlog",
                    "path": f"issues/{item.id}/",
                }
                for item in tasks
            ]
        elif kind == "defect" and row.repair_issue_id:
            item = (
                Issue.issue_objects.filter(project_id=self.project_id, pk=row.repair_issue_id)
                .select_related("state")
                .first()
            )
            if item:
                schedule = [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "start": item.start_date,
                        "target": item.target_date,
                        "status": item.state.group if item.state_id else "backlog",
                        "path": f"issues/{item.id}/",
                    }
                ]
        linked = []
        if not ProjectMember.objects.filter(
            project_id=self.project_id, member=request.user, is_active=True, role__gte=15
        ).exists():
            versions = []
        for version in versions:
            state = flow_projection(version)
            if version.start_date or version.target_date:
                schedule.append(
                    {
                        "id": str(version.id),
                        "name": f"版本 {version.version} · {version.name}",
                        "start": version.start_date,
                        "target": version.target_date,
                        "status": version.status,
                        "path": f"versions?version={version.id}&display=timeline",
                    }
                )
            linked.append(
                {
                    "id": str(version.id),
                    "name": version.name,
                    "version": version.version,
                    "milestones": [
                        {
                            "id": node["id"],
                            "name": node["name"],
                            "date": node.get("target_date"),
                            "status": state.get(node["id"], {}).get("status", "waiting"),
                        }
                        for node in version.flow_nodes
                        if node["kind"] == "milestone"
                    ],
                }
            )
        return Response(
            {
                "current": current,
                "stages": [{"key": key, "name": name} for key, name in stages],
                "events": events,
                "event_pagination": pagination,
                "dates": dates,
                "versions": linked,
                "schedule": schedule,
            }
        )
