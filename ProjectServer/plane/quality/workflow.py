# SPDX-License-Identifier: AGPL-3.0-only
"""Managed test plans reuse existing frozen revisions and execution evidence."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from plane.db.models import ProjectMember
from .permissions import strict, capable, require_assignee, has_role
from .models import PlanEvent, TestPlan
from .serializers import PlanSerializer, plan_summary
from .views import Conflict, QualityView, plan_queryset


class WorkflowInput(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["assign", "claim", "pause", "resume", "submit", "approve", "return", "cancel"]
    )
    expected_version = serializers.IntegerField(min_value=1)
    assignee_id = serializers.UUIDField(required=False)
    comment = serializers.CharField(max_length=4000, allow_blank=True, default="")


class PlanWorkflow(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(WorkflowInput)
        plan = get_object_or_404(TestPlan.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if hasattr(plan, "defect_verification"):
            raise Conflict("请从缺陷详情提交、验收或退回本轮验证。")
        if plan.archived_at:
            raise Conflict("计划已归档，请先恢复。")
        if not plan.managed:
            raise Conflict("普通测试计划不使用分派验收流程。")
        if plan.workflow_version != data["expected_version"]:
            raise Conflict("计划已由其他人更新，请刷新后操作。")
        action = data["action"]
        if action in {"claim", "resume"}:
            from .test_resources import require_ready

            require_ready(plan)
        manager = (
            (strict(self.project_id) and capable(self.project_id, request.user.id, "manage_test"))
            or not strict(self.project_id)
            and ProjectMember.objects.filter(
                project=plan.project, member=request.user, is_active=True, role=20
            ).exists()
        )
        scheduler = manager or (
            strict(self.project_id) and capable(self.project_id, request.user.id, "manage_test_plan")
        )
        if (action in {"approve", "return"} and not manager) or (action in {"assign", "cancel"} and not scheduler):
            raise PermissionDenied("当前角色不能分派或验收测试。")
        previous = plan.status
        transitions = {
            "assign": ({"pending", "ready", "returned"}, "ready"),
            "claim": ({"pending", "ready", "returned"}, "running"),
            "pause": ({"running"}, "paused"),
            "resume": ({"paused"}, "running"),
            "submit": ({"running"}, "review"),
            "approve": ({"review"}, "completed"),
            "return": ({"review"}, "returned"),
            "cancel": ({"pending", "ready", "running", "paused", "review", "returned"}, "cancelled"),
        }
        allowed, target = transitions[action]
        if previous not in allowed:
            raise Conflict("当前状态不允许此操作，请刷新计划。")
        if action == "assign":
            assignee = data.get("assignee_id")
            if not assignee:
                raise ValidationError({"assignee_id": "请选择测试负责人。"})
            self.validate_assignee(assignee)
            require_assignee(self, assignee, "REGRESSION_TESTER")
            if not ProjectMember.objects.filter(
                project=plan.project, member_id=assignee, is_active=True, role__gte=15
            ).exists():
                raise ValidationError({"assignee_id": "不能把测试分派给只读访客。"})
            plan.assignee_id = assignee
        elif action == "claim":
            if (
                plan.assignee_id
                and plan.assignee_id != request.user.id
                and not has_role(self.project_id, request.user.id, "PLATFORM_ADMIN")
            ):
                raise PermissionDenied("此计划已经分派给其他测试员。")
            if not plan.assignee_id:
                plan.assignee = request.user
        elif (
            action in {"pause", "resume", "submit"}
            and plan.assignee_id != request.user.id
            and not has_role(self.project_id, request.user.id, "PLATFORM_ADMIN")
        ):
            raise PermissionDenied("只有当前测试负责人可以操作。")
        snapshot = plan_queryset().get(pk=plan.pk)
        execution_ids = []
        if action in {"submit", "approve"}:
            summary = plan_summary(snapshot)
            if not summary["total"] or summary["pending"]:
                raise ValidationError(
                    {"error": "请记录本轮全部用例的实际结果，再提交验收；失败、阻塞、无法判定和跳过也应如实反馈。"}
                )
            if action == "approve" and summary["inconclusive"]:
                raise ValidationError(
                    {"result": "本轮存在无法判定的结果，请退回补采或处理环境后重新验证，不能确认完成。"}
                )
            if action == "approve" and summary["passed"] != summary["total"] and not data["comment"].strip():
                raise ValidationError({"comment": "本轮存在失败、阻塞或跳过，请说明结果确认意见；这不代表允许发布。"})
            execution_ids = [str(item.latest_results[0].id) for item in snapshot.items.all()]
        if action in {"return", "cancel"} and not data["comment"].strip():
            raise ValidationError({"comment": "请填写退回或取消原因。"})
        from .data_regression import transition

        target = transition(plan, action, request.user, data["comment"]) or target
        event_round = plan.round_no
        if action == "return":
            plan.round_no += 1
        if action == "approve":
            plan.reviewed_by = request.user
            plan.reviewed_at = timezone.now()
        plan.status = target
        plan.workflow_version += 1
        plan.save()
        from .notifications import plan_notice

        plan_notice(plan, action, request.user)
        PlanEvent.objects.create(
            plan=plan,
            project=plan.project,
            created_by=request.user,
            action=action,
            previous_status=previous,
            status=target,
            round_no=event_round,
            note=data["comment"],
            execution_ids=execution_ids,
        )
        return Response(PlanSerializer(plan_queryset().get(pk=plan.pk)).data)
