# SPDX-License-Identifier: AGPL-3.0-only
"""Safe integration inventory and authority checks, never credential echo or remote writes."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import PlatformProject, PlatformIdentity, DaqBinding
from .roles import management
from .views import QualityView, Conflict, QualityPagination
from . import platform


class IntegrationInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["project", "identity", "binding"])
    id = serializers.UUIDField()
    expected_active = serializers.BooleanField()
    active = serializers.BooleanField()


class IntegrationOverview(QualityView):
    def get(self, request, **kwargs):
        management(self)
        project = self.project()
        summary = request.query_params.get("summary") == "1"
        kind = request.query_params.get("kind")
        if kind is not None:
            kind = serializers.ChoiceField(choices=["project", "identity", "binding"]).run_validation(kind)
            search = serializers.CharField(max_length=160, allow_blank=True).run_validation(
                request.query_params.get("search", "")
            )
            models = {"project": PlatformProject, "identity": PlatformIdentity, "binding": DaqBinding}
            fields = {
                "project": ["source_instance", "name", "external_project_id"],
                "identity": ["source_instance", "user__username", "user__display_name", "external_user_id"],
                "binding": ["source_instance", "source_record_id", "package_id", "platform_task_id"],
            }
            query = models[kind].objects.filter(project=project).order_by("-created_at", "-id")
            if search:
                condition = Q()
                for field in fields[kind]:
                    condition |= Q(**{field + "__icontains": search})
                query = query.filter(condition)
            if kind == "identity":
                query = query.select_related("user")
            paginator = QualityPagination()
            page = paginator.paginate_queryset(query, request, view=self)
            return paginator.get_paginated_response([inventory_row(row, kind) for row in page])
        projects = []
        for row in PlatformProject.objects.filter(project=project):
            try:
                config = platform.configuration(row.source_instance)
                configured = bool(config.get("service_token"))
            except platform.PlatformUnavailable:
                configured = False
            projects.append(
                {
                    "id": str(row.id),
                    "source_instance": row.source_instance,
                    "external_project_id": row.external_project_id,
                    "name": row.name,
                    "active": row.active,
                    "authority_configured": configured,
                }
            )
        identities = [
            {
                "id": str(row.id),
                "source_instance": row.source_instance,
                "external_user_id": row.external_user_id,
                "user_id": str(row.user_id),
                "name": row.user.display_name,
                "active": row.active,
            }
            for row in (
                PlatformIdentity.objects.none()
                if summary
                else PlatformIdentity.objects.filter(project=project).select_related("user")
            )
        ]
        bindings = [
            {
                "id": str(row.id),
                "source_instance": row.source_instance,
                "task_id": row.platform_task_id,
                "session_id": row.source_record_id,
                "package_id": row.package_id,
                "active": row.active,
            }
            for row in (
                DaqBinding.objects.none()
                if summary
                else DaqBinding.objects.filter(project=project).order_by("-created_at")[:100]
            )
        ]
        return Response(
            {
                "projects": projects,
                "identities": identities,
                "bindings": bindings,
                "counts": {
                    "project": PlatformProject.objects.filter(project=project).count(),
                    "identity": PlatformIdentity.objects.filter(project=project).count(),
                    "active_identity": PlatformIdentity.objects.filter(project=project, active=True).count(),
                    "binding": DaqBinding.objects.filter(project=project).count(),
                },
                "notice": "配置状态、权威接口校验、实际业务联调分别验收；此处不显示服务凭据，也不会修改外部平台。",
            }
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        management(self)
        data = self.input(IntegrationInput)
        model = {"project": PlatformProject, "identity": PlatformIdentity, "binding": DaqBinding}[data["kind"]]
        row = get_object_or_404(model.objects.select_for_update(), pk=data["id"], project_id=self.project_id)
        if row.active != data["expected_active"]:
            raise Conflict()
        row.active = data["active"]
        row.save(update_fields=["active"])
        return Response({"id": str(row.id), "active": row.active})


def inventory_row(row, kind):
    result = {"id": str(row.id), "source_instance": row.source_instance, "active": row.active}
    if kind == "project":
        try:
            configured = bool(platform.configuration(row.source_instance).get("service_token"))
        except platform.PlatformUnavailable:
            configured = False
        result.update(external_project_id=row.external_project_id, name=row.name, authority_configured=configured)
    elif kind == "identity":
        result.update(external_user_id=row.external_user_id, user_id=str(row.user_id), name=row.user.display_name)
    else:
        result.update(task_id=row.platform_task_id, session_id=row.source_record_id, package_id=row.package_id)
    return result


class CheckInput(serializers.Serializer):
    source_instance = serializers.CharField(max_length=120)
    task_id = serializers.IntegerField(min_value=1)
    source_session_id = serializers.CharField(max_length=255, allow_blank=True, default="")


class IntegrationCheck(QualityView):
    def post(self, request, **kwargs):
        management(self)
        data = self.input(CheckInput)
        mappings = PlatformProject.objects.filter(
            project_id=self.project_id, source_instance=data["source_instance"], active=True
        )
        params = {"sourceSessionId": data["source_session_id"]} if data["source_session_id"] else None
        context = platform.fetch(
            data["source_instance"], f"/internal/issue-integration/tasks/{data['task_id']}/context", params
        )
        if (
            not isinstance(context, dict)
            or not mappings.filter(external_project_id=context.get("projectId")).exists()
            or context.get("taskId") != data["task_id"]
            or (data["source_session_id"] and context.get("sourceSessionId") != data["source_session_id"])
        ):
            raise ValidationError({"error": "权威接口返回的项目、任务或Session归属不匹配。"})
        return Response(
            {
                "status": "authority_verified",
                "task": {
                    key: context.get(key)
                    for key in [
                        "projectId",
                        "taskId",
                        "taskName",
                        "sourceSessionId",
                        "dataPackageId",
                        "deviceName",
                        "collectedAt",
                    ]
                },
                "notice": "仅验证真实权威接口与映射归属，不代表已完成采集、上传或业务回归。",
            }
        )
