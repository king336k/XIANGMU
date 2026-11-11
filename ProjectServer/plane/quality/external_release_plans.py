"""Import an authorized external plan snapshot; never deploy or write to the source."""

import hashlib
import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.response import Response
from . import platform
from .models import PlatformProject, PlatformIdentity
from .external_release_models import ExternalReleaseSnapshot
from .views import QualityView, QualityPagination, Conflict
from .assets import manager


class ImportInput(serializers.Serializer):
    source_instance = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,80}$", required=False)
    external_project_id = serializers.IntegerField(min_value=1, required=False)
    mapping_id = serializers.UUIDField(required=False)
    request_id = serializers.UUIDField()


def response_data(row):
    return {
        "id": str(row.id),
        "source_instance": row.source_instance,
        "external_project_id": row.external_project_id,
        "version": row.version,
        "status": row.status,
        "rows": row.rows,
        "sha256": row.sha256,
        "created_at": row.created_at,
        "confirmed_at": row.confirmed_at,
        "scope": "来源计划的同步快照；不代表本平台已准入或软件已部署。",
    }


def validate_rows(payload, project_id):
    if (
        not isinstance(payload, dict)
        or type(payload.get("total")) is not int
        or not isinstance(payload.get("items"), list)
        or not 0 <= payload["total"] <= 1000
        or len(payload["items"]) != payload["total"]
    ):
        raise platform.PlatformUnavailable("外部计划清单不完整，未保存同步记录。")
    rows = []
    seen = set()

    class Row(serializers.Serializer):
        id = serializers.IntegerField(min_value=1)
        project_id = serializers.IntegerField(min_value=1)
        plan_key = serializers.CharField(max_length=255)
        name = serializers.CharField(max_length=255)
        description = serializers.CharField(max_length=20000, allow_blank=True, default="")
        status = serializers.CharField(max_length=80, allow_blank=True, default="")
        source_url = serializers.URLField(max_length=1000, allow_blank=True, default="")
        synced_at = serializers.DateTimeField(required=False, allow_null=True)

    for raw in payload["items"]:
        item = Row(data=raw)
        if not item.is_valid() or item.validated_data["project_id"] != project_id or item.validated_data["id"] in seen:
            raise platform.PlatformUnavailable("外部计划包含重复、归属不符或无效记录。")
        value = item.validated_data
        seen.add(value["id"])
        if value.get("synced_at"):
            value["synced_at"] = value["synced_at"].isoformat()
        rows.append(value)
    return rows


def authority(view, source, external_project_id):
    manager(view)
    mapping = get_object_or_404(
        PlatformProject,
        project_id=view.project_id,
        source_instance=source,
        external_project_id=external_project_id,
        active=True,
    )
    config = platform.configuration(source)
    if config.get("kind") != "legacy_hub" or config.get("directory_auth", "bearer") != "bearer":
        raise platform.PlatformUnavailable("此来源暂未提供授权的发布计划读取接口。")
    identity = PlatformIdentity.objects.filter(
        project_id=view.project_id, source_instance=source, user=view.request.user, active=True
    ).first()
    if not identity:
        raise PermissionDenied("请先建立当前账号在来源项目的可信身份。")
    platform.verify_identity(identity, external_project_id)
    return mapping


class ExternalReleasePlans(QualityView):
    def get(self, request, **kwargs):
        manager(self)
        pager = QualityPagination()
        rows = pager.paginate_queryset(ExternalReleaseSnapshot.objects.filter(project=self.project()), request)
        return pager.get_paginated_response([response_data(row) for row in rows])


class ExternalReleasePreview(QualityView):
    def get(self, request, **kwargs):
        manager(self)
        choices = []
        for mapping in PlatformProject.objects.filter(project=self.project(), active=True):
            try:
                config = platform.configuration(mapping.source_instance)
            except platform.PlatformUnavailable:
                continue
            if config.get("kind") == "legacy_hub":
                choices.append(
                    {
                        "id": str(mapping.id),
                        "source_instance": mapping.source_instance,
                        "external_project_id": mapping.external_project_id,
                        "label": f"{mapping.name or mapping.source_instance} · 项目 {mapping.external_project_id}",
                    }
                )
        pager = QualityPagination()
        rows = pager.paginate_queryset(choices, request)
        return pager.get_paginated_response(rows)

    def post(self, request, **kwargs):
        data = self.input(ImportInput)
        if data.get("mapping_id"):
            mapping = get_object_or_404(
                PlatformProject, pk=data.pop("mapping_id"), project_id=self.project_id, active=True
            )
            data["source_instance"] = mapping.source_instance
            data["external_project_id"] = mapping.external_project_id
        if not data.get("source_instance") or not data.get("external_project_id"):
            raise ValidationError({"source": "请选择已关联的来源项目。"})
        authority(self, data["source_instance"], data["external_project_id"])
        existing = ExternalReleaseSnapshot.objects.filter(
            project_id=self.project_id, request_id=data["request_id"]
        ).first()
        if existing:
            if (
                existing.source_instance != data["source_instance"]
                or existing.external_project_id != data["external_project_id"]
            ):
                raise Conflict("同一请求编号不能读取其他来源。")
            return Response(response_data(existing))
        rows = validate_rows(
            platform.fetch(
                data["source_instance"], "/api/test-center/release-plan", {"projectId": data["external_project_id"]}
            ),
            data["external_project_id"],
        )
        # No database lock is held during the external read.
        with transaction.atomic():
            manager(self)
            if (
                not PlatformProject.objects.filter(
                    project_id=self.project_id,
                    source_instance=data["source_instance"],
                    external_project_id=data["external_project_id"],
                    active=True,
                ).exists()
                or not PlatformIdentity.objects.filter(
                    project_id=self.project_id, source_instance=data["source_instance"], user=request.user, active=True
                ).exists()
            ):
                raise PermissionDenied("来源授权已变更，请重新核对。")
            project = self.project()
            type(project).objects.select_for_update().get(pk=project.pk)
            prior = ExternalReleaseSnapshot.objects.filter(project=project, request_id=data["request_id"]).first()
            if prior:
                if (prior.source_instance != data["source_instance"]
                    or prior.external_project_id != data["external_project_id"]):
                    raise Conflict("同一请求编号不能读取其他来源。")
                return Response(response_data(prior))
            row = ExternalReleaseSnapshot.objects.create(
                project=project,
                created_by=request.user,
                source_instance=data["source_instance"],
                external_project_id=data["external_project_id"],
                request_id=data["request_id"],
                rows=rows,
                sha256=hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            )
        return Response(response_data(row), status=201)


class ExternalReleaseConfirm(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        row = get_object_or_404(ExternalReleaseSnapshot.objects.select_for_update(), pk=pk, project_id=self.project_id)
        authority(self, row.source_instance, row.external_project_id)
        version = serializers.IntegerField(min_value=1).run_validation(request.data.get("expected_version"))
        if row.status == "confirmed":
            return Response(response_data(row))
        if row.version != version:
            raise Conflict()
        row.status = "confirmed"
        row.version += 1
        row.confirmed_by = request.user
        row.confirmed_at = timezone.now()
        row.save()
        return Response(response_data(row))
