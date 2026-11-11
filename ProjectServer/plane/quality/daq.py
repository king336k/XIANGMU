# SPDX-License-Identifier: AGPL-3.0-only
"""DAQ boundary: native identity, operator-verified task bindings, repeatable receipts."""

import hashlib
import json
from uuid import UUID
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from .models import DaqBinding, DaqReport, Defect, DefectEvent
from .permissions import strict, capable, writable_member
from .views import QualityView, Conflict, QualityPagination
from plane.authentication.session import BaseSessionAuthentication
from .identity import PlatformBridgeAuthentication


class DaqView(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]


def verify_request_binding(view, binding):
    from .platform import verify_binding, verify_identity
    from .models import PlatformIdentity

    context = verify_binding(binding)
    if isinstance(view.request.auth, dict):
        identity = PlatformIdentity.objects.get(
            project_id=binding.project_id,
            source_instance=binding.source_instance,
            external_user_id=view.request.auth["external_user_id"],
            user=view.request.user,
            active=True,
        )
        verify_identity(identity, context.get("projectId"))
    return context


class DaqContext(DaqView):
    def get(self, request, **kwargs):
        from .permissions import ROLE_NAMES, roles_for

        project = self.project()
        return Response(
            {
                "project_id": str(project.id),
                "project_name": project.name,
                "workspace": self.workspace_slug,
                "identifier": project.identifier,
                "user_id": str(request.user.id),
                "username": request.user.display_name or request.user.username,
                "roles": [
                    ROLE_NAMES[role] for role in sorted(roles_for(project.id, request.user.id)) if role in ROLE_NAMES
                ],
                "can_report": writable_member(project.id, request.user.id, self.workspace_slug)
                and capable(project.id, request.user.id, "report"),
            }
        )


class DaqProjectResolve(DaqContext):
    from .identity import ProjectResolveBridgeAuthentication

    authentication_classes = [ProjectResolveBridgeAuthentication]


class DaqIssueDetail(DaqView):
    def get(self, request, pk, **kwargs):
        from django.shortcuts import get_object_or_404
        from .models import ProblemPackage, DataRegression
        from .serializers import DefectSerializer
        from .views import defect_queryset
        from .attachments import FileSerializer
        from .data_regression import information
        from .diagnostics import DiagnosticSerializer, expire_stale

        defect = get_object_or_404(defect_queryset(), pk=pk, project=self.project())
        reports = DaqReport.objects.filter(defect=defect, binding__active=True).select_related("binding")
        if isinstance(request.auth, dict) and request.auth.get("source_instance"):
            reports = reports.filter(binding__source_instance=request.auth["source_instance"])
        report = get_object_or_404(reports)
        if isinstance(request.auth, dict):
            verify_request_binding(self, report.binding)
        expire_stale(defect)
        packages = ProblemPackage.objects.filter(defect=defect).prefetch_related("uploaded_files__created_by")
        return Response(
            {
                "defect": DefectSerializer(defect).data,
                "source": receipt(report, self),
                "packages": [
                    {
                        "id": str(row.id),
                        "name": row.name,
                        "files": FileSerializer(row.uploaded_files.all(), many=True).data,
                    }
                    for row in packages
                ],
                "diagnostics": DiagnosticSerializer(defect.diagnostics.order_by("-created_at")[:5], many=True).data,
                "regressions": [
                    information(row) for row in DataRegression.objects.filter(defect=defect).order_by("created_at")
                ],
            }
        )


class BindingInput(serializers.Serializer):
    source_instance = serializers.CharField(max_length=120)
    platform_task_id = serializers.IntegerField(min_value=1)
    source_record_id = serializers.CharField(max_length=255)
    issue_id = serializers.UUIDField()
    device = serializers.CharField(max_length=255, allow_blank=True, default="")
    package_id = serializers.CharField(max_length=255, allow_blank=True, default="")


class DaqInput(serializers.Serializer):
    sourceRecordId = serializers.CharField(max_length=255)
    platformTaskId = serializers.IntegerField(min_value=1)
    category = serializers.ChoiceField(
        choices=["UploadError", "DataAnomaly", "ValidationFailed", "TimestampAnomaly", "Other"]
    )
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=10000)
    sourceSnapshot = serializers.CharField(max_length=16000, required=False, allow_blank=True)

    def validate_sourceSnapshot(self, value):
        if value:
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                raise serializers.ValidationError("来源快照必须是有效JSON。")
            if not isinstance(parsed, (dict, list)):
                raise serializers.ValidationError("来源快照必须是JSON对象或数组。")
        return value


class BindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DaqBinding
        fields = [
            "id",
            "source_instance",
            "platform_task_id",
            "source_record_id",
            "issue_id",
            "device",
            "package_id",
            "active",
            "created_at",
        ]


def manager(view):
    from plane.db.models import ProjectMember

    if strict(view.project_id):
        allowed = capable(view.project_id, view.request.user.id, "manage_test")
    else:
        allowed = ProjectMember.objects.filter(
            project_id=view.project_id, member=view.request.user, is_active=True, role=20
        ).exists()
    if not allowed:
        raise PermissionDenied("只有项目经理可以核对和登记DAQ来源映射。")


class DaqBindings(QualityView):
    def get(self, request, **kwargs):
        manager(self)
        return self.listing(DaqBinding.objects.filter(project=self.project()), BindingSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        manager(self)
        data = self.input(BindingInput)
        self.validate_issue(data["issue_id"])
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        existing = DaqBinding.objects.filter(
            project=project, platform_task_id=data["platform_task_id"], source_record_id=data["source_record_id"]
        ).first()
        if existing:
            if any(getattr(existing, key) != value for key, value in data.items()):
                raise Conflict("来源映射已存在且内容不同，不能改写已核对的任务关系。")
            return Response(BindingSerializer(existing).data)
        row = DaqBinding.objects.create(project=project, created_by=request.user, **data)
        return Response(BindingSerializer(row).data, status=201)


def receipt(report, view):
    source = report.binding
    group = source.reports.order_by("created_at", "id")
    ids = list(group.values_list("id", flat=True))
    return {
        "issueId": str(report.defect_id),
        "issueCode": report.defect.code,
        "platformProjectId": source.external_project_id,
        "sourceRecordId": source.source_record_id,
        "platformTaskId": source.platform_task_id,
        "status": report.defect.status,
        "category": report.category,
        "description": report.defect.description,
        "createdAt": report.created_at,
        "submissionOrdinal": ids.index(report.id) + 1,
        "sourceIssueCount": len(ids),
        "nativeUrl": f"/{view.workspace_slug}/p/{report.defect.project.identifier}/defects/?defect={report.defect_id}",
        "capabilities": {"canViewIssue": True, "canRunRegression": False},
    }


def bind_new_session(view, data, project):
    """A trusted new Session may reuse an unambiguous task mapping, never a browser package claim."""
    from .models import PlatformProject
    from . import platform

    source = view.request.auth["source_instance"]
    bindings = DaqBinding.objects.filter(
        project=project, source_instance=source, platform_task_id=data["platformTaskId"], active=True
    ).select_related("issue")
    issues = list(bindings.order_by().values_list("issue_id", flat=True).distinct()[:2])
    if len(issues) != 1:
        raise Conflict("当前采集任务的项目关联不明确，请联系管理员核对。")
    original = bindings.first()
    if original.issue.project_id != project.id or original.issue.deleted_at or original.issue.archived_at:
        raise Conflict("关联任务已归档或移除，请联系管理员核对。")
    mappings = PlatformProject.objects.filter(project=project, source_instance=source, active=True)
    if not mappings.exists():
        raise PermissionDenied("来源项目关联已撤销。")
    context = platform.fetch(
        source,
        f"/internal/issue-integration/tasks/{data['platformTaskId']}/context",
        {"sourceSessionId": data["sourceRecordId"]},
    )
    package = context.get("dataPackageId") if isinstance(context, dict) else None
    if (
        not isinstance(context, dict)
        or context.get("taskId") != data["platformTaskId"]
        or not mappings.filter(external_project_id=context.get("projectId")).exists()
        or context.get("sourceSessionId") != data["sourceRecordId"]
        or not isinstance(package, (str, int))
        or isinstance(package, bool)
        or not str(package).strip()
        or len(str(package)) > 255
    ):
        raise PermissionDenied("数据平台中的采集记录、任务或数据包归属不匹配。")
    return DaqBinding.objects.create(
        project=project,
        created_by=view.request.user,
        source_instance=source,
        platform_task_id=data["platformTaskId"],
        source_record_id=data["sourceRecordId"],
        external_project_id=context["projectId"],
        issue=original.issue,
        package_id=str(package),
        device=str(context.get("deviceName") or "")[:255],
    )


class DaqReports(DaqView):
    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(DaqInput)
        try:
            key = UUID(request.headers.get("Idempotency-Key", ""))
        except (ValueError, TypeError):
            raise ValidationError({"Idempotency-Key": "请提供本次上报的UUID，重试须使用相同编号。"})
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        scope = DaqBinding.objects.filter(
            project=project,
            platform_task_id=data["platformTaskId"],
            source_record_id=data["sourceRecordId"],
        )
        binding = scope.filter(active=True).first()
        if (
            not binding
            and not scope.exists()
            and isinstance(request.auth, dict)
            and request.auth.get("source_instance")
        ):
            binding = bind_new_session(self, data, project)
        if not binding:
            from django.http import Http404

            raise Http404("采集任务尚未完成项目关联，请联系管理员。")
        if not binding.issue_id or binding.issue.project_id != project.id:
            raise Conflict("任务项目关系已经变更，请重新核对来源映射。")
        if isinstance(request.auth, dict) and request.auth.get("source_instance"):
            if request.auth["source_instance"] != binding.source_instance:
                raise PermissionDenied("来源实例与认证身份不匹配。")
            context = verify_request_binding(self, binding)
            if binding.external_project_id is None:
                binding.external_project_id = context.get("projectId")
                binding.save(update_fields=["external_project_id"])
        fingerprint = hashlib.sha256(JSONRenderer().render(data)).hexdigest()
        existing = (
            DaqReport.objects.filter(project=project, created_by=request.user, request_id=key)
            .select_related("binding", "defect")
            .first()
        )
        if existing:
            if existing.request_hash != fingerprint:
                raise Conflict("同一上报编号不能对应不同内容。")
            return Response(receipt(existing, self))
        defect = Defect.objects.create(
            project=project, created_by=request.user, title=data["title"], description=data["description"]
        )
        report = DaqReport.objects.create(
            project=project,
            created_by=request.user,
            binding=binding,
            defect=defect,
            category=data["category"],
            request_id=key,
            request_hash=fingerprint,
        )
        DefectEvent.objects.create(
            project=project,
            created_by=request.user,
            defect=defect,
            status="open",
            note="DAQ Session异常上报；任务关系来自服务端已核对映射。",
        )
        from .diagnostics import schedule_automatic

        schedule_automatic(defect, request.user, "daq_report", context=json.loads(data.get("sourceSnapshot") or "{}"))
        return Response(receipt(report, self), status=201)


class SourceQuery(serializers.Serializer):
    sourceRecordId = serializers.CharField(max_length=255)
    platformTaskId = serializers.IntegerField(min_value=1)


class QueryInput(serializers.Serializer):
    records = SourceQuery(many=True, allow_empty=False, max_length=100)


class DaqQuery(DaqView):
    def post(self, request, **kwargs):
        data = self.input(QueryInput)
        pairs = {(row["platformTaskId"], row["sourceRecordId"]) for row in data["records"]}
        exact = Q(pk__in=[])
        for task, record in pairs:
            exact |= Q(binding__platform_task_id=task, binding__source_record_id=record)
        reports = (
            DaqReport.objects.filter(exact, project=self.project(), binding__active=True)
            .select_related("binding", "defect")
            .order_by("-created_at", "-id")
        )
        source = request.auth.get("source_instance") if isinstance(request.auth, dict) else None
        if source:
            reports = reports.filter(binding__source_instance=source)
        paginator = QualityPagination() if "page" in request.query_params else None
        if paginator:
            reports = paginator.paginate_queryset(reports, request)
        if source:
            for binding in {row.binding_id: row.binding for row in reports}.values():
                verify_request_binding(self, binding)
        rows = [receipt(row, self) for row in reports]
        return paginator.get_paginated_response(rows) if paginator else Response(rows)


class IdentityInput(serializers.Serializer):
    source_instance = serializers.CharField(max_length=120)
    external_user_id = serializers.IntegerField(min_value=1)
    user_id = serializers.UUIDField()


class DaqIdentities(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        from .models import PlatformIdentity
        from .permissions import writable_member

        from .roles import management

        management(self)
        data = self.input(IdentityInput)
        if not writable_member(self.project_id, data["user_id"], self.workspace_slug):
            raise ValidationError({"user_id": "被映射账号必须是当前项目和工作区的有效成员。"})
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        old = PlatformIdentity.objects.filter(
            project=project, source_instance=data["source_instance"], external_user_id=data["external_user_id"]
        ).first()
        if old:
            if old.user_id != data["user_id"]:
                raise Conflict("已有平台身份不能改绑到其他账号。")
            return Response({"id": str(old.id), "active": old.active})
        row = PlatformIdentity.objects.create(project=project, created_by=request.user, **data)
        return Response({"id": str(row.id), "active": row.active}, status=201)


class PlatformProjectInput(serializers.Serializer):
    source_instance = serializers.CharField(max_length=120)
    external_project_id = serializers.IntegerField(min_value=1)
    name = serializers.CharField(max_length=255, allow_blank=True, default="")


class DaqProjectMapping(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        from .roles import management
        from .models import PlatformProject

        management(self)
        data = self.input(PlatformProjectInput)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        prior = PlatformProject.objects.filter(
            project=project, source_instance=data["source_instance"], external_project_id=data["external_project_id"]
        ).first()
        if prior:
            return Response({"id": str(prior.id), "active": prior.active})
        row = PlatformProject.objects.create(project=project, created_by=request.user, **data)
        return Response({"id": str(row.id), "active": row.active}, status=201)


class DaqAvailableSources(QualityView):
    def get(self, request, **kwargs):
        return self.listing(DaqBinding.objects.filter(project=self.project(), active=True), BindingSerializer)
