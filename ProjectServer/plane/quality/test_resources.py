# SPDX-License-Identifier: AGPL-3.0-only
"""Resource readiness is a prerequisite, never an execution result or device control."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from .authorship import AuthoredRecordSerializer
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .models import FieldAgent, TestResource, PlanResource, TestPlan, QualityLifecycleEvent
from .permissions import writable_member, capable, strict
from .data_regression import manager


def test_scheduler(project_id, user):
    return capable(project_id, user.id, "manage_test_plan") if strict(project_id) else manager(project_id, user)
from .serializers import PlanSerializer
from .views import QualityView, Conflict, plan_queryset


class ResourceInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    kind = serializers.ChoiceField(choices=["robot", "daq_station", "server", "environment", "other"])
    status = serializers.ChoiceField(choices=["available", "offline", "maintenance", "disabled"], default="available")
    build = serializers.CharField(max_length=120, allow_blank=True, default="")
    description = serializers.CharField(max_length=4000, allow_blank=True, default="")
    agent_id = serializers.UUIDField(required=False, allow_null=True)
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{0,80}$", allow_blank=True, default="")
    external_id = serializers.CharField(max_length=255, allow_blank=True, default="")
    expected_version = serializers.IntegerField(min_value=1, required=False)


class ResourceSerializer(AuthoredRecordSerializer):
    class Meta:
        model = TestResource
        fields = [
            "id",
            "name",
            "kind",
            "status",
            "build",
            "description",
            "agent_id",
            "source_instance",
            "external_id",
            "edit_version",
        ]


class TestResources(QualityView):
    def get(self, request, **kwargs):
        return self.listing(
            TestResource.objects.filter(project=self.project()).order_by("name", "id"), ResourceSerializer
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        if not test_scheduler(self.project_id, request.user):
            raise PermissionDenied("测试资源由有测试管理权限的成员维护。")
        data = self.input(ResourceInput)
        data.pop("expected_version", None)
        validate_agent(self, data)
        row = TestResource.objects.create(project=self.project(), created_by=request.user, **data)
        return Response(ResourceSerializer(row).data, status=201)


def validate_agent(view, data):
    if data.get("agent_id") and not FieldAgent.objects.filter(project_id=view.project_id, pk=data["agent_id"]).exists():
        raise ValidationError({"agent_id": "请选择当前项目登记的现场代理。"})


class TestResourceDetail(QualityView):
    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        if not test_scheduler(self.project_id, request.user):
            raise PermissionDenied("测试资源由有测试管理权限的成员维护。")
        data = self.input(ResourceInput, partial=True)
        project = self.project()
        row = get_object_or_404(TestResource.objects.select_for_update(), pk=pk, project=project)
        if data.pop("expected_version", None) != row.edit_version:
            raise Conflict()
        validate_agent(self, data)
        for key, value in data.items():
            setattr(row, key, value)
        row.edit_version += 1
        row.save()
        QualityLifecycleEvent.objects.create(
            project=project,
            created_by=request.user,
            resource="test_resource",
            object_id=row.id,
            action="edit",
            reason="调整资源登记状态或版本；不表示已执行测试。",
            before_version=row.edit_version - 1,
            after_version=row.edit_version,
        )
        return Response(ResourceSerializer(row).data)


def preflight(plan):
    from .resources import AGENT_ONLINE_SECONDS
    from .models import PlatformIdentity
    from . import platform
    from rest_framework.exceptions import AuthenticationFailed

    resources, errors = [], []
    for link in plan.resource_links.select_related("resource__agent__project__workspace", "resource__agent__owner"):
        row = link.resource
        problems = []
        if row.project_id != plan.project_id:
            problems.append("资源不属于当前项目。")
        if row.status != "available":
            problems.append("资源当前状态不可用。")
        if row.build and row.build != plan.build:
            problems.append("资源登记版本与被测版本不一致。")
        agent = row.agent
        if agent and (
            agent.project_id != plan.project_id
            or not agent.enabled
            or not agent.owner.is_active
            or not agent.last_seen_at
            or (timezone.now() - agent.last_seen_at).total_seconds() >= AGENT_ONLINE_SECONDS
            or not writable_member(plan.project_id, agent.owner_id, plan.project.workspace.slug)
            or not capable(plan.project_id, agent.owner_id, "report")
        ):
            problems.append("现场代理停用、离线或负责数采员已失效。")
        if agent and agent.source_instance:
            identity = PlatformIdentity.objects.filter(
                project_id=plan.project_id, source_instance=agent.source_instance, user_id=agent.owner_id, active=True
            ).first()
            if identity is None:
                problems.append("现场代理的外部身份映射已失效。")
            else:
                try:
                    platform.verify_identity(identity)
                except AuthenticationFailed:
                    problems.append("现场代理的来源账号或项目权限已撤销。")
                except platform.PlatformUnavailable:
                    problems.append("现场代理的权威身份核验暂不可用。")
        resources.append(
            {
                "id": str(row.id),
                "name": row.name,
                "kind": row.kind,
                "status": row.status,
                "build": row.build,
                "edit_version": row.edit_version,
                "agent_id": str(row.agent_id) if row.agent_id else None,
                "agent_last_seen_at": agent.last_seen_at.isoformat() if agent and agent.last_seen_at else None,
                "errors": problems,
            }
        )
        errors.extend([row.name + "：" + problem for problem in problems])
    if not plan.build.strip() or not plan.environment.strip():
        errors.append("请补齐被测版本与环境。")
    return {
        "ready": not errors,
        "errors": errors,
        "resources": resources,
        "checked_at": timezone.now().isoformat(),
        "notice": "资源检查仅核对当前登记、版本与近期心跳，不代表测试通过、实际设备控制或OTA发布。",
    }


def require_ready(plan):
    resource_ids = plan.resource_links.values_list("resource_id", flat=True)
    rows = list(TestResource.objects.select_for_update().filter(pk__in=resource_ids).order_by("id"))
    list(
        FieldAgent.objects.select_for_update()
        .filter(pk__in=[row.agent_id for row in rows if row.agent_id])
        .order_by("id")
    )
    result = preflight(plan)
    if not result["ready"]:
        raise ValidationError({"resources": result["errors"]})
    return result


class Preflight(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(preflight(self.obj(TestPlan, pk)))


class ResourceSelection(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    resource_ids = serializers.ListField(child=serializers.UUIDField(), max_length=20)


class PlanResources(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if not test_scheduler(self.project_id, request.user):
            raise PermissionDenied("测试资源由有测试管理权限的成员安排。")
        data = self.input(ResourceSelection)
        plan = get_object_or_404(TestPlan.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if (
            plan.workflow_version != data["expected_version"]
            or plan.archived_at
            or plan.status not in {"pending", "ready", "returned"}
            or plan.items.filter(executions__isnull=False).exists()
        ):
            raise Conflict("已有执行历史或当前阶段不能更换资源，请复制新计划。")
        ids = set(data["resource_ids"])
        if TestResource.objects.filter(project_id=self.project_id, pk__in=ids).count() != len(ids):
            raise ValidationError({"resource_ids": "资源不存在或不属于当前项目。"})
        plan.resource_links.all().delete()
        PlanResource.objects.bulk_create(
            [PlanResource(project=plan.project, created_by=request.user, plan=plan, resource_id=pk) for pk in ids]
        )
        plan.workflow_version += 1
        plan.save(update_fields=["workflow_version"])
        QualityLifecycleEvent.objects.create(
            project=plan.project,
            created_by=request.user,
            resource="test_plan",
            object_id=plan.id,
            action="select_resources",
            reason="更新计划执行资源，执行结果另行记录。",
            before_version=plan.workflow_version - 1,
            after_version=plan.workflow_version,
        )
        return Response(PlanSerializer(plan_queryset().get(pk=plan.pk)).data)
