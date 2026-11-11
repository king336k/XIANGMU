# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
import json
import unicodedata
from pathlib import PurePosixPath
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .permissions import require_assignee
from .models import Defect, DefectComment, DefectEvent, ProblemPackage, SourceLink
from .serializers import DefectSerializer
from .authorship import AuthoredRecordSerializer
from .views import Conflict, QualityView, defect_queryset
from plane.authentication.session import BaseSessionAuthentication
from .identity import PlatformBridgeAuthentication


class SourceInput(serializers.Serializer):
    source_system = serializers.CharField(max_length=64)
    source_instance = serializers.CharField(max_length=120)
    record_type = serializers.CharField(max_length=64)
    record_id = serializers.CharField(max_length=255)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=20000, allow_blank=True, default="")
    task_id = serializers.CharField(max_length=255, allow_blank=True, default="")
    package_id = serializers.CharField(max_length=255, allow_blank=True, default="")
    device = serializers.CharField(max_length=255, allow_blank=True, default="")


class SourceSerializer(serializers.ModelSerializer):
    source_context = serializers.SerializerMethodField()

    def get_source_context(self, obj):
        from .daq_incidents import SYSTEM, TYPE, signed_record

        if obj.source_system != SYSTEM or obj.record_type != TYPE:
            return None
        record = signed_record(obj)
        if not record:
            return None
        payload = record["payload"]
        context = record.get("sourceContext", {})
        return {
            "platformProjectId": payload["platformProjectId"],
            "platformProjectName": context.get("projectName", ""),
            "platformTaskId": payload.get("platformTaskId"),
            "platformTaskName": context.get("taskName", ""),
            "sourceReference": payload.get("sourceReference", ""),
        }

    class Meta:
        model = SourceLink
        fields = [
            "id",
            "source_system",
            "source_instance",
            "record_type",
            "record_id",
            "task_id",
            "package_id",
            "device",
            "created_at",
            "source_context",
        ]


class SourceDefect(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(SourceInput)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        key = {name: data[name] for name in ["source_system", "source_instance", "record_type", "record_id"]}
        existing = SourceLink.objects.filter(project=project, **key).first()
        if existing:
            if any(getattr(existing, field) != data[field] for field in ["task_id", "package_id", "device"]):
                raise Conflict("同一来源编号的设备、任务或数据包关系不同，请核对来源记录。")
            return Response(
                {
                    "source": SourceSerializer(existing).data,
                    "defect": DefectSerializer(defect_queryset().get(pk=existing.defect_id)).data,
                }
            )
        title, description = data.pop("title"), data.pop("description")
        defect = Defect.objects.create(project=project, created_by=request.user, title=title, description=description)
        link = SourceLink.objects.create(project=project, created_by=request.user, defect=defect, **data)
        DefectEvent.objects.create(
            project=project,
            created_by=request.user,
            defect=defect,
            status="open",
            note="从来源记录创建；不表示外部任务状态已改变。",
        )
        return Response(
            {
                "source": SourceSerializer(link).data,
                "defect": DefectSerializer(defect_queryset().get(pk=defect.pk)).data,
            },
            status=201,
        )


class CollaborationInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=["claim", "comment"])
    content = serializers.CharField(max_length=10000, allow_blank=True, default="")
    visibility = serializers.ChoiceField(choices=["public", "internal"], default="public")


class CommentSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="created_by.display_name", default="成员")

    class Meta:
        model = DefectComment
        fields = ["id", "content", "visibility", "actor", "created_at"]


class DefectCollaboration(QualityView):
    def get(self, request, pk, **kwargs):
        defect = self.obj(Defect, pk)
        from .collaboration_admin import internal_access

        comments = defect.comments.select_related("created_by")
        if not internal_access(self.project_id, request.user, self.workspace_slug):
            comments = comments.filter(visibility="public")
        return self.listing(comments, CommentSerializer)

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(CollaborationInput)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data["action"] == "claim":
            require_assignee(self, request.user.id, "TECHNICIAN")
            if defect.status not in {"open", "in_progress"}:
                raise Conflict("当前缺陷不在可认领阶段。")
            if defect.assignee_id and defect.assignee_id != request.user.id:
                raise PermissionDenied("缺陷已分派给其他处理人。")
            if defect.assignee_id == request.user.id and defect.status == "in_progress":
                return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)
            old_status = defect.status
            defect.assignee = request.user
            defect.status = "in_progress"
            defect.edit_version += 1
            defect.save()
            DefectEvent.objects.create(
                project=defect.project,
                defect=defect,
                created_by=request.user,
                previous_status=old_status,
                status="in_progress",
                note="处理人认领",
            )
            return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)
        if not data["content"].strip():
            raise ValidationError({"content": "请填写评论内容。"})
        from .collaboration_admin import internal_access

        if data["visibility"] == "internal" and not internal_access(self.project_id, request.user, self.workspace_slug):
            raise PermissionDenied("当前成员只能发表数采员可见回复。")
        comment = DefectComment.objects.create(
            project=defect.project,
            defect=defect,
            created_by=request.user,
            content=data["content"],
            visibility=data["visibility"],
        )
        from .notifications import defect_notice

        # Notification content is a fixed event label; private text is never copied to inboxes.
        if comment.visibility == "public":
            defect_notice(defect, request.user, "新增公开协作回复")
        return Response(CommentSerializer(comment).data, status=201)


class FileManifest(serializers.Serializer):
    path = serializers.CharField(max_length=500)
    size = serializers.IntegerField(min_value=0, max_value=200 * 1024 * 1024)
    sha256 = serializers.RegexField(regex=r"^[a-fA-F0-9]{64}$")

    def validate_path(self, value):
        normalized = unicodedata.normalize("NFC", value.replace("\\", "/"))
        if (
            ":" in normalized
            or "\x00" in normalized
            or normalized.startswith("/")
            or any(part in {"", ".", ".."} for part in normalized.split("/"))
        ):
            raise serializers.ValidationError("文件路径必须是包内相对路径，不能包含上级目录。")
        if PurePosixPath(normalized).is_absolute():
            raise serializers.ValidationError("不接受绝对路径。")
        return normalized


class PackageInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    defect_id = serializers.UUIDField()
    source_system = serializers.CharField(max_length=64)
    external_id = serializers.CharField(max_length=255)
    files = FileManifest(many=True, allow_empty=False, max_length=1000)

    def validate_files(self, files):
        if len({f["path"] for f in files}) != len(files):
            raise serializers.ValidationError("清单中存在重复文件路径。")
        if sum(f["size"] for f in files) > 500 * 1024 * 1024:
            raise serializers.ValidationError("问题包清单总大小不能超过500MB。")
        return files


class PackageSerializer(AuthoredRecordSerializer):
    class Meta:
        model = ProblemPackage
        fields = ["id", "defect_id", "name", "source_system", "external_id", "files", "status", "created_at"]


class PackagePreflight(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def post(self, request, **kwargs):
        data = self.input(PackageInput)
        self.obj(Defect, data["defect_id"])
        return Response(
            {
                "valid": True,
                "file_count": len(data["files"]),
                "total_bytes": sum(f["size"] for f in data["files"]),
                "scope": "仅校验元数据清单，文件内容上传与校验另行完成。",
            }
        )


class PackageList(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def get(self, request, **kwargs):
        qs = ProblemPackage.objects.filter(project=self.project())
        if request.query_params.get("defect_id"):
            pk = serializers.UUIDField().run_validation(request.query_params["defect_id"])
            qs = qs.filter(defect_id=pk)
        return self.listing(qs, PackageSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(PackageInput)
        defect = self.obj(Defect, data.pop("defect_id"))
        type(defect.project).objects.select_for_update().get(pk=defect.project_id)
        fingerprint = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        existing = ProblemPackage.objects.filter(
            project_id=self.project_id, source_system=data["source_system"], external_id=data["external_id"]
        ).first()
        if existing:
            if existing.manifest_hash != fingerprint or existing.defect_id != defect.id:
                raise Conflict("同一外部问题包编号的内容或关联对象不同。")
            return Response(PackageSerializer(existing).data)
        package = ProblemPackage.objects.create(
            project=defect.project, defect=defect, created_by=request.user, manifest_hash=fingerprint, **data
        )
        return Response(PackageSerializer(package).data, status=201)


class DefectSources(QualityView):
    def get(self, request, pk, **kwargs):
        from .models import DaqReport

        defect = self.obj(Defect, pk)
        sources = list(SourceSerializer(defect.sources.all(), many=True).data)
        for report in DaqReport.objects.filter(defect=defect).select_related("binding"):
            source = report.binding
            sources.append(
                {
                    "id": str(report.id),
                    "source_system": "ENGRAM_DAQ",
                    "source_instance": source.source_instance,
                    "record_type": "DAQ_SESSION",
                    "record_id": source.source_record_id,
                    "task_id": str(source.platform_task_id),
                    "package_id": source.package_id,
                    "device": source.device,
                    "created_at": report.created_at,
                }
            )
        return Response(sources)
