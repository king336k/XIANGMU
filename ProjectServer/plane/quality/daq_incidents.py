"""Signed DAQ startup/recording incidents without fabricated Session or package evidence."""

import hashlib
import json
from datetime import timedelta

from django.core import signing
from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from . import platform
from .daq import DaqView
from .models import Defect, DefectEvent, PlatformIdentity, PlatformProject, SourceLink
from .permissions import has_role, writable_member
from .views import Conflict

SYSTEM = "ENGRAM_DAQ"
TYPE = "daq_incident"
SALT = "quality.daq.incident.v1"


class StrictInput(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("请提交JSON对象。")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "不支持此参数。" for key in unknown})
        return super().to_internal_value(data)


class PositiveId(serializers.IntegerField):
    def __init__(self, **kwargs):
        super().__init__(min_value=1, max_value=2**63 - 1, **kwargs)

    def to_internal_value(self, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise serializers.ValidationError("必须是正整数编号。")
        return super().to_internal_value(value)


class SafeEnvironment(StrictInput):
    phase = serializers.CharField(max_length=120, required=False)
    rosMode = serializers.CharField(max_length=40, required=False)
    clientVersion = serializers.CharField(max_length=120, required=False)
    os = serializers.CharField(max_length=120, required=False)
    errorCode = serializers.CharField(max_length=120, required=False)


class IncidentInput(StrictInput):
    eventId = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=["startup_failure", "recording_failure"])
    occurredAt = serializers.CharField(max_length=80)
    platformProjectId = PositiveId()
    platformTaskId = PositiveId(required=False)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=10000)
    device = serializers.CharField(max_length=255, allow_blank=True, default="")
    environment = SafeEnvironment(required=False)
    category = serializers.ChoiceField(
        choices=["UploadError", "DataAnomaly", "ValidationFailed", "TimestampAnomaly", "Other"], required=False
    )
    sourceReference = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_occurredAt(self, value):
        try:
            stamp = parse_datetime(value)
        except ValueError:
            stamp = None
        if stamp is None or timezone.is_naive(stamp) or stamp > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError("发生时间须带时区，且不能晚于服务器时间5分钟。")
        return stamp.isoformat()


class SessionInput(StrictInput):
    sourceSessionId = serializers.CharField(max_length=255)
    platformTaskId = PositiveId(required=False)


def fingerprint(data):
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def signed_record(link):
    prefetched = getattr(link.defect, "_incident_signature_events", None)
    notes = (
        (event.note for event in prefetched)
        if prefetched is not None
        else DefectEvent.objects.filter(defect=link.defect, status="open", previous_status="").values_list(
            "note", flat=True
        )
    )
    for note in notes:
        try:
            envelope = json.loads(note)
            record = signing.loads(envelope["incidentSignature"], salt=SALT)
            if (
                record.get("linkId") == str(link.id)
                and record.get("defectId") == str(link.defect_id)
                and record.get("projectId") == str(link.project_id)
                and record.get("sourceInstance") == link.source_instance
                and record.get("recordId") == link.record_id
                and record.get("actorId") == str(link.created_by_id)
                and str(record.get("payload", {}).get("platformTaskId", "")) == link.task_id
                and record.get("requestHash") == fingerprint(record.get("payload"))
                and link.source_system == SYSTEM
                and link.record_type == TYPE
                and link.package_id == ""
            ):
                return record
        except (ValueError, TypeError, KeyError, signing.BadSignature):
            continue
    return None


def trusted_incident(defect):
    for link in SourceLink.objects.filter(defect=defect, source_system=SYSTEM, record_type=TYPE).select_related(
        "defect", "project__workspace", "created_by"
    ):
        if signed_record(link):
            return link
    return None


def verify_authority(project, actor, source, external_actor, external_project, task=None):
    identity = PlatformIdentity.objects.filter(
        project=project,
        source_instance=source,
        external_user_id=external_actor,
        user=actor,
        user__is_active=True,
        active=True,
    ).first()
    if (
        not identity
        or not writable_member(project.id, actor.id, project.workspace.slug)
        or not has_role(project.id, actor.id, "REPORTER")
        or not PlatformProject.objects.filter(
            project=project, source_instance=source, external_project_id=external_project, active=True
        ).exists()
    ):
        raise PermissionDenied("来源身份、数采员职责或项目关联不可用。")
    user = platform.fetch(source, f"/internal/issue-users/{external_actor}")
    if (
        not isinstance(user, dict)
        or user.get("id") != external_actor
        or user.get("active") is not True
        or user.get("role") != "Collector"
    ):
        raise PermissionDenied("当前来源账号未授予数采员职责。")
    platform.verify_identity(identity, external_project)
    if task is None:
        return {"projectId": external_project, "taskId": None, "sourceSessionId": None, "dataPackageId": None}
    context = platform.fetch(source, f"/internal/issue-integration/tasks/{task}/context")
    if (
        not isinstance(context, dict)
        or type(context.get("taskId")) is not int
        or type(context.get("projectId")) is not int
        or context.get("taskId") != task
        or context.get("projectId") != external_project
    ):
        raise PermissionDenied("来源任务不属于当前授权项目。")
    return context


def verify_incident_authority(link):
    record = signed_record(link)
    if record is None:
        raise PermissionDenied("异常来源签名无效。")
    return record["payload"]


def bridge(view):
    auth = view.request.auth
    if not isinstance(auth, dict) or not auth.get("source_instance") or type(auth.get("external_user_id")) is not int:
        raise PermissionDenied("此入口仅接受DAQ服务签发的可信身份。")
    return auth["source_instance"], auth["external_user_id"]


def own_incident(view, pk):
    source, actor = bridge(view)
    defect = get_object_or_404(Defect, project=view.project(), pk=pk)
    link = trusted_incident(defect)
    if (
        link is None
        or link.source_instance != source
        or link.created_by_id != view.request.user.id
        or not link.record_id.startswith(str(actor) + ":")
    ):
        raise PermissionDenied("只能读取自己在当前来源上报的异常。")
    verify_incident_authority(link)
    return link


def verified_sessions(incident):
    return [
        session
        for session in SourceLink.objects.filter(
            defect=incident.defect, source_system=SYSTEM, record_type="verified_session"
        ).order_by("-created_at", "-id")
        if session_record(incident, session)
    ]


def receipt(link, view, session=None):
    from .agent_lifecycle import agent_processing
    sessions = verified_sessions(link)
    if session is None:
        session = sessions[0] if sessions else None
    record = signed_record(link)
    data = record["payload"]
    return {
        "issueId": str(link.defect_id),
        "issueCode": link.defect.code,
        "status": link.defect.status,
        "agent_processing": agent_processing(link.defect),
        "eventId": data["eventId"],
        "hubProjectId": str(link.project_id),
        "category": data.get("category", "Other"),
        "sourceReference": data.get("sourceReference", ""),
        "platformProjectName": record.get("sourceContext", {}).get("projectName", ""),
        "platformTaskName": record.get("sourceContext", {}).get("taskName", ""),
        "reporter": record.get("reporter", {}),
        "sourceRecordType": data["kind"],
        "occurredAt": data["occurredAt"],
        "platformProjectId": data.get("platformProjectId"),
        "platformTaskId": data.get("platformTaskId"),
        "sourceSessionId": session.record_id if session else None,
        "dataPackageId": session.package_id if session else None,
        "linkedPlatformTaskId": int(session.task_id) if session else None,
        "verifiedSessions": [
            {
                "sourceSessionId": row.record_id,
                "dataPackageId": row.package_id,
                "platformTaskId": int(row.task_id),
            }
            for row in sessions
        ],
        "diagnosticStatus": "waiting_materials"
        if not link.defect.diagnostics.exists()
        else link.defect.diagnostics.latest("created_at").status,
        "nativeUrl": f"/{view.workspace_slug}/p/{link.project.identifier}/defects/?defect={link.defect_id}",
        "capabilities": {"canViewIssue": True, "canRunRegression": False, "canLoginPlatform": False},
    }


class DaqIncidents(DaqView):
    def get(self, request, **kwargs):
        source, actor = bridge(self)
        query = {}
        for key in ("platformProjectId", "platformTaskId"):
            raw = request.query_params.get(key)
            if raw is None and key == "platformTaskId":
                continue
            if raw is None or len(raw) > 19 or not raw.isascii() or not raw.isdigit():
                raise serializers.ValidationError({key: "必须是正整数编号。"})
            query[key] = PositiveId().run_validation(int(raw))
        project = self.project()
        verify_authority(project, request.user, source, actor, query["platformProjectId"], query.get("platformTaskId"))
        return Response(
            {
                "can_report": True,
                "platformProjectId": query["platformProjectId"],
                "platformTaskId": query.get("platformTaskId"),
                "project_name": project.name,
                "username": request.user.display_name or request.user.username,
            }
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        source, actor = bridge(self)
        data = self.input(self.input_serializer if hasattr(self, "input_serializer") else IncidentInput)
        data.pop("hubProjectId", None)
        data["eventId"] = str(data["eventId"])
        project = self.project()
        if not getattr(self, "report_only", False):
            raise PermissionDenied("旧来源上报入口已停用。")
        key = f"{actor}:{data['eventId']}"
        lock = int.from_bytes(hashlib.sha256((source + ":" + key).encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
        link = (
            SourceLink.objects.filter(source_system=SYSTEM, source_instance=source, record_type=TYPE, record_id=key)
            .select_related("defect", "project")
            .first()
        )
        if link:
            if link.project_id != project.id or link.created_by_id != request.user.id:
                raise PermissionDenied("此异常事件不属于当前上报范围。")
            record = signed_record(link)
            if record is None or record["requestHash"] != fingerprint(data):
                raise Conflict("同一事件编号不能对应不同内容。")
            from .module_routing import initial_assign
            link.defect = initial_assign(link.defect, request.user)
            return Response(receipt(link, self))
        from .defect_content import defect_content

        title, description = defect_content(data["title"], data["description"])
        defect = Defect.objects.create(
            project=project,
            created_by=request.user,
            title=title,
            description=description,
            verification_scope="functional",
            severity="",
            severity_origin="pending",
        )
        link = SourceLink.objects.create(
            project=project,
            created_by=request.user,
            defect=defect,
            source_system=SYSTEM,
            source_instance=source,
            record_type=TYPE,
            record_id=key,
            task_id=str(data.get("platformTaskId", "")),
            package_id="",
            device=data["device"],
        )
        record = {
            "linkId": str(link.id),
            "defectId": str(defect.id),
            "projectId": str(project.id),
            "sourceInstance": source,
            "actorId": str(request.user.id),
            "externalActor": actor,
            "reporter": request.auth.get("reporter", {}),
            "recordId": key,
            "requestHash": fingerprint(data),
            "payload": data,
            **({"authorityMode": "report_only"} if getattr(self, "report_only", False) else {}),
        }
        DefectEvent.objects.create(
            project=project,
            created_by=request.user,
            defect=defect,
            status="open",
            note=json.dumps(
                {
                    "message": "DAQ启动或采集异常，等待真实诊断材料；事件不是采集Session。",
                    "incidentSignature": signing.dumps(record, salt=SALT, compress=True),
                },
                ensure_ascii=False,
            ),
        )
        from .module_routing import initial_assign
        link.defect = initial_assign(defect, request.user)
        return Response(receipt(link, self), status=201)


class DaqIncidentDetail(DaqView):
    def get(self, request, pk, **kwargs):
        from .attachments import FileSerializer
        from .data_regression import information
        from .diagnostics import DiagnosticSerializer, expire_stale
        from .models import DataRegression, ProblemPackage
        from .serializers import DefectSerializer
        from .views import defect_queryset

        link = own_incident(self, pk)
        expire_stale(link.defect)
        result = receipt(link, self)
        result.update(
            {
                "defect": DefectSerializer(defect_queryset().get(pk=pk)).data,
                "diagnostics": DiagnosticSerializer(
                    link.defect.diagnostics.order_by("-created_at")[:5], many=True
                ).data,
                "packages": [
                    {
                        "id": str(row.id),
                        "name": row.name,
                        "files": FileSerializer(row.uploaded_files.all(), many=True).data,
                    }
                    for row in ProblemPackage.objects.filter(defect=link.defect).prefetch_related(
                        "uploaded_files__created_by"
                    )
                ],
                "regressions": [
                    information(row) for row in DataRegression.objects.filter(defect=link.defect).order_by("created_at")
                ],
            }
        )
        return Response(result)


def session_record(incident, session):
    for note in DefectEvent.objects.filter(defect=incident.defect).values_list("note", flat=True):
        try:
            record = signing.loads(json.loads(note)["incidentSessionSignature"], salt=SALT + ".session")
            if (
                record
                == {
                    "incidentId": str(incident.id),
                    "sessionLinkId": str(session.id),
                    "defectId": str(incident.defect_id),
                    "projectId": str(incident.project_id),
                    "sourceInstance": session.source_instance,
                    "taskId": session.task_id,
                    "sessionId": session.record_id,
                    "packageId": session.package_id,
                }
                and session.source_system == SYSTEM
                and session.record_type == "verified_session"
                and session.project_id == incident.project_id
                and session.defect_id == incident.defect_id
                and session.source_instance == incident.source_instance
            ):
                return record
        except (ValueError, TypeError, KeyError, signing.BadSignature):
            continue
    return None


def real_session_context(link, task, session_id):
    original = signed_record(link)["payload"]
    context = platform.fetch(
        link.source_instance, f"/internal/issue-integration/tasks/{task}/context", {"sourceSessionId": session_id}
    )
    package = context.get("dataPackageId") if isinstance(context, dict) else None
    if (
        not isinstance(context, dict)
        or type(context.get("taskId")) is not int
        or type(context.get("projectId")) is not int
        or context.get("taskId") != task
        or context.get("projectId") != original["platformProjectId"]
        or context.get("sourceSessionId") != session_id
        or type(package) not in [str, int]
        or not str(package).strip()
        or len(str(package)) > 255
    ):
        raise PermissionDenied("来源真实Session、任务或数据包归属不匹配。")
    return context


def regression_binding(defect, actor):
    """Turn a verified real Session into a baseline binding, never an incident UUID."""
    from .models import DaqBinding

    link = trusted_incident(defect)
    if link is None:
        from django.http import Http404

        raise Http404("未找到采集异常来源。")
    verify_incident_authority(link)
    sessions = verified_sessions(link)
    session = sessions[0] if sessions else None
    if session is None:
        raise Conflict("请先关联实际采集任务、Session和数据包，再发起重新采集回归。")
    if (
        not defect.repair_issue_id
        or defect.repair_issue.project_id != defect.project_id
        or defect.repair_issue.deleted_at
        or defect.repair_issue.archived_at
    ):
        raise Conflict("请先关联当前项目有效的技术修复工作项。")
    context = real_session_context(link, int(session.task_id), session.record_id)
    if str(context["dataPackageId"]) != session.package_id:
        raise PermissionDenied("关联Session的数据包已经变更。")
    type(defect.project).objects.select_for_update().get(pk=defect.project_id)
    binding = DaqBinding.objects.filter(
        project=defect.project, platform_task_id=int(session.task_id), source_record_id=session.record_id
    ).first()
    if binding:
        if (
            not binding.active
            or binding.source_instance != link.source_instance
            or binding.external_project_id != context["projectId"]
            or binding.package_id != session.package_id
            or binding.issue_id != defect.repair_issue_id
        ):
            raise Conflict("实际Session已有不同来源关联，请先核对。")
        return binding
    binding = DaqBinding.objects.create(
        project=defect.project,
        created_by=actor,
        source_instance=link.source_instance,
        platform_task_id=int(session.task_id),
        source_record_id=session.record_id,
        external_project_id=context["projectId"],
        issue=defect.repair_issue,
        package_id=session.package_id,
        device=session.device,
    )
    DefectEvent.objects.create(
        project=defect.project,
        created_by=actor,
        defect=defect,
        previous_status=defect.status,
        status=defect.status,
        note="已核对后续真实Session及数据包，作为重新采集回归的基线；原异常事件保持不变。",
    )
    return binding


class DaqIncidentSession(DaqView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        link = own_incident(self, pk)
        data = self.input(SessionInput)
        record = signed_record(link)
        original_task = record["payload"].get("platformTaskId")
        task = data.get("platformTaskId", original_task)
        if task is None:
            raise Conflict("请选择后续实际采集任务，不能推测Session归属。")
        if original_task is not None and task != original_task:
            raise Conflict("后续Session必须属于原异常的采集任务。")
        context = real_session_context(link, task, data["sourceSessionId"])
        package = context["dataPackageId"]
        scope = f"{link.project_id}:{link.source_instance}:{data['sourceSessionId']}"
        lock = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock])
        Defect.objects.select_for_update().get(pk=link.defect_id)
        existing = SourceLink.objects.filter(
            project=link.project,
            source_system=SYSTEM,
            source_instance=link.source_instance,
            record_type="verified_session",
            record_id=data["sourceSessionId"],
        ).first()
        if existing:
            if (
                existing.defect_id != link.defect_id
                or existing.task_id != str(task)
                or existing.package_id != str(package)
                or not session_record(link, existing)
            ):
                raise Conflict("该Session已经关联另一异常或来源关系已改变。")
            return Response(receipt(link, self, existing))
        session = SourceLink.objects.create(
            project=link.project,
            created_by=request.user,
            defect=link.defect,
            source_system=SYSTEM,
            source_instance=link.source_instance,
            record_type="verified_session",
            record_id=data["sourceSessionId"],
            task_id=str(task),
            package_id=str(package),
            device=link.device,
        )
        session_data = {
            "incidentId": str(link.id),
            "sessionLinkId": str(session.id),
            "defectId": str(link.defect_id),
            "projectId": str(link.project_id),
            "sourceInstance": session.source_instance,
            "taskId": session.task_id,
            "sessionId": session.record_id,
            "packageId": session.package_id,
        }
        DefectEvent.objects.create(
            project=link.project,
            created_by=request.user,
            defect=link.defect,
            previous_status=link.defect.status,
            status=link.defect.status,
            note=json.dumps(
                {
                    "message": "已关联后续实际采集Session和数据包；不作为本轮修复回归证据。",
                    "incidentSessionSignature": signing.dumps(session_data, salt=SALT + ".session", compress=True),
                },
                ensure_ascii=False,
            ),
        )
        return Response(receipt(link, self, session), status=201)
