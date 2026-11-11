"""Signed DAQ report-only access never creates project membership or business duties."""

from django.db import transaction
from django.db.models import F, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.db.models import Project
from .identity import PlatformBridgeAuthentication
from .models import DefectEvent, SourceLink, ProblemPackage, PackageFile
from .daq_incidents import DaqIncidents, IncidentInput, signed_record, receipt, TYPE, SYSTEM
from .sources import PackageList
from .attachments import PackageFiles, FileDownload, ImagePreview
from .views import QualityPagination


class DaqReportingAuthentication(PlatformBridgeAuthentication):
    def key_config(self, key_id):
        import json
        import os
        from django.conf import settings

        keys = getattr(settings, "QUALITY_DAQ_REPORT_KEYS", None)
        if keys is None:
            keys = json.loads(os.environ.get("QUALITY_DAQ_REPORT_KEYS_JSON", "{}"))
        config = keys.get(key_id)
        if not config or config.get("enabled", True) is not True:
            return None
        source = config.get("source_instance")
        if not isinstance(source, str) or not source or len(source) > 120:
            raise AuthenticationFailed("DAQ来源配置无效。")
        from .daq_project_grants import granted_projects

        return {**config, "projects": granted_projects()}

    @transaction.atomic
    def authenticate(self, request):
        import hashlib
        import json
        from plane.db.models import User

        verified = self.verified_principal(request)
        if verified is None:
            return None
        config, external_actor = verified
        principal = json.loads(request.headers["X-Issue-Principal"])
        username = principal.get("username")
        if not isinstance(username, str) or not username.strip() or len(username) > 128:
            raise AuthenticationFailed("DAQ当前登录账号信息无效。")
        source = config["source_instance"]
        # One non-login service actor per device source, never one platform account per collector.
        name = "daq-service-" + hashlib.sha256(source.encode()).hexdigest()[:32]
        user, created = User.objects.get_or_create(
            username=name,
            defaults={
                "email": name + "@accounts.invalid",
                "display_name": "DAQ反馈服务",
                "is_bot": True,
            },
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        if not user.is_bot or not user.is_active or user.has_usable_password():
            raise AuthenticationFailed("DAQ反馈服务账号配置无效。")
        return user, {
            "source_instance": source,
            "external_user_id": external_actor,
            "daq_report_only": True,
            "projects": config["projects"],
            "reporter": {"id": external_actor, "username": username.strip()},
        }


class ReportingView(BaseAPIView):
    authentication_classes = [DaqReportingAuthentication]
    permission_classes = [IsAuthenticated]

    def allow_project(self, project_id):
        if str(project_id) not in self.request.auth["projects"]:
            raise PermissionDenied("此DAQ未获准向当前项目反馈。")

    def bind_project(self, project):
        self.allow_project(project.id)
        self.kwargs.update(project_id=project.id, slug=project.workspace.slug)

    def own_report(self, report_id):
        auth = self.request.auth
        link = get_object_or_404(
            SourceLink.objects.select_related("project__workspace", "defect", "created_by"),
            defect_id=report_id,
            source_system=SYSTEM,
            record_type=TYPE,
            source_instance=auth["source_instance"],
            created_by=self.request.user,
            project__deleted_at__isnull=True,
            project__workspace__deleted_at__isnull=True,
        )
        record = signed_record(link)
        if (
            not record
            or record.get("authorityMode") != "report_only"
            or record.get("externalActor") != auth["external_user_id"]
            or link.project.archived_at
        ):
            raise PermissionDenied("只能访问本人上报的有效故障。")
        self.allow_project(link.project_id)
        self.bind_project(link.project)
        return link

    def project(self):
        return get_object_or_404(
            Project, pk=self.project_id, archived_at__isnull=True, workspace__deleted_at__isnull=True
        )

    def obj(self, model, pk, **filters):
        return get_object_or_404(model, pk=pk, project_id=self.project_id, **filters)

    def input(self, serializer, partial=False):
        data = serializer(data=self.request.data, partial=partial)
        data.is_valid(raise_exception=True)
        return data.validated_data


class DaqProjectOptions(ReportingView):
    def get(self, request):
        query = (
            Project.objects.filter(
                id__in=request.auth["projects"], archived_at__isnull=True, workspace__deleted_at__isnull=True
            )
            .select_related("workspace")
            .order_by("name", "id")
        )
        search = serializers.CharField(max_length=200, allow_blank=True).run_validation(
            request.query_params.get("search", "")
        )
        if search:
            query = query.filter(Q(name__icontains=search) | Q(identifier__icontains=search))
        paginator = QualityPagination()
        rows = paginator.paginate_queryset(query, request)
        return paginator.get_paginated_response(
            [
                {
                    "hubProjectId": str(row.id),
                    "projectName": row.name,
                    "identifier": row.identifier,
                    "workspace": row.workspace.slug,
                }
                for row in rows
            ]
        )


class ReportInput(IncidentInput):
    platformProjectId = serializers.IntegerField(min_value=1, required=False)
    hubProjectId = serializers.UUIDField()


class DaqReports(ReportingView):
    report_only = True
    input_serializer = ReportInput

    def get(self, request):
        status = serializers.ChoiceField(
            choices=["open", "in_progress", "resolved", "closed"], allow_blank=True
        ).run_validation(request.query_params.get("status", ""))
        search = (
            serializers.CharField(max_length=200, allow_blank=True)
            .run_validation(request.query_params.get("search", ""))
            .casefold()
        )
        wanted = request.query_params.get("sourceReference")
        if wanted is not None:
            wanted = serializers.CharField(max_length=255, allow_blank=True).run_validation(wanted)
        query = (
            SourceLink.objects.filter(
                source_system=SYSTEM,
                record_type=TYPE,
                source_instance=request.auth["source_instance"],
                created_by=request.user,
                record_id__startswith=str(request.auth["external_user_id"]) + ":",
                project__archived_at__isnull=True,
                project__deleted_at__isnull=True,
                project__workspace__deleted_at__isnull=True,
            )
            .select_related("project__workspace", "defect")
            .prefetch_related(
                Prefetch(
                    "defect__events",
                    queryset=DefectEvent.objects.filter(status="open", previous_status="").only("defect_id", "note"),
                    to_attr="_incident_signature_events",
                )
            )
            .order_by("-created_at", "-id")
        )
        if request.query_params.get("hubProjectId"):
            query = query.filter(
                project_id=serializers.UUIDField().run_validation(request.query_params["hubProjectId"])
            )
        query = query.filter(project_id__in=request.auth["projects"])
        links = list(query)
        from .numbering import preload

        preload([link.defect for link in links])
        counts = dict.fromkeys(["all", "open", "in_progress", "resolved", "closed"], 0)
        rows = []
        for link in links:
            record = signed_record(link)
            if (
                not record
                or record.get("authorityMode") != "report_only"
                or record.get("externalActor") != request.auth["external_user_id"]
            ):
                continue
            data = record["payload"]
            if wanted is not None and data.get("sourceReference", "") != wanted:
                continue
            if search and not any(
                search in value.casefold()
                for value in [
                    link.defect.code,
                    link.defect.title,
                    link.defect.description,
                    data.get("sourceReference", ""),
                ]
            ):
                continue
            counts["all"] += 1
            if link.defect.status in counts:
                counts[link.defect.status] += 1
            if not status or link.defect.status == status:
                rows.append(link)
        paginator = QualityPagination()
        page = paginator.paginate_queryset(rows, request)
        results = []
        for link in page:
            self.bind_project(link.project)
            results.append(
                {
                    **receipt(link, self),
                    "title": link.defect.title,
                    "created_at": link.defect.created_at,
                    "updated_at": link.defect.updated_at,
                }
            )
        response = paginator.get_paginated_response(results)
        response.data["status_counts"] = counts
        return response

    @transaction.atomic
    def post(self, request):
        data = self.input(ReportInput)
        project = get_object_or_404(
            Project.objects.select_related("workspace"),
            pk=data["hubProjectId"],
            archived_at__isnull=True,
            workspace__deleted_at__isnull=True,
        )
        self.bind_project(project)
        return DaqIncidents.post(self, request)


class DaqOwnReportDetail(ReportingView):
    def get(self, request, report_id):
        link = self.own_report(report_id)
        defect = link.defect
        return Response(
            {
                "defect": {
                    "id": str(defect.id),
                    "code": defect.code,
                    "title": defect.title,
                    "status": defect.status,
                    "created_at": defect.created_at,
                    "updated_at": defect.updated_at,
                },
                "source": receipt(link, self),
                "timeline": report_timeline(defect),
            }
        )


def report_timeline(defect):
    def actor_name(actor):
        return (actor.display_name or actor.username) if actor is not None else "系统"

    from .daq_incidents import trusted_incident

    source = trusted_incident(defect)
    reporter = signed_record(source).get("reporter", {}) if source else {}
    timeline = [
        {
            "id": "created:" + str(defect.id),
            "actor": reporter.get("username") or actor_name(defect.created_by),
            "action": "提交反馈",
            "created_at": defect.created_at,
            "status": "open",
        }
    ]
    actions = {"in_progress": "开始处理", "resolved": "提交回归", "closed": "验收关闭", "open": "重新打开"}
    events = (
        defect.events.select_related("created_by")
        .exclude(previous_status="")
        .exclude(previous_status=F("status"))
        .filter(status__in=actions)
        .order_by("created_at", "id")
    )
    for event in events:
        timeline.append(
            {
                "id": str(event.id),
                "actor": actor_name(event.created_by),
                "action": actions[event.status],
                "created_at": event.created_at,
                "status": event.status,
            }
        )
    from .models import TestExecution

    result_actions = {"passed": "回归通过", "failed": "回归失败", "blocked": "回归未完成", "inconclusive": "回归未完成"}
    related_execution = Q(
        item__plan__data_regression__project_id=defect.project_id,
        item__plan__data_regression__defect=defect,
    )
    if (
        defect.verification_scope == "functional"
        and defect.status == "closed"
        and defect.regression_execution_id
        and defect.case_id
        and defect.resolved_at
    ):
        related_execution |= Q(
            pk=defect.regression_execution_id,
            item__case_id=defect.case_id,
            item__revision__project_id=defect.project_id,
            item__revision__case_id=defect.case_id,
            item__plan__build=defect.fixed_build,
            result="passed",
            created_at__gt=defect.resolved_at,
        )
    executions = TestExecution.objects.filter(
        related_execution,
        project_id=defect.project_id,
        item__project_id=defect.project_id,
        item__plan__project_id=defect.project_id,
        item__case__project_id=defect.project_id,
        result__in=result_actions,
    ).select_related("created_by")
    for execution in executions:
        timeline.append(
            {
                "id": "execution:" + str(execution.id),
                "actor": actor_name(execution.created_by),
                "action": result_actions[execution.result],
                "created_at": execution.created_at,
                "status": None,
            }
        )
    timeline.sort(key=lambda row: (row["created_at"], row["id"]))
    current_status = "open"
    for row in timeline:
        if row["status"] is None:
            row["status"] = current_status
        else:
            current_status = row["status"]
    return timeline


class DaqOwnReportPackages(ReportingView):
    def post(self, request, report_id):
        link = self.own_report(report_id)
        if str(request.data.get("defect_id")) != str(link.defect_id):
            raise PermissionDenied("附件只能关联本次上报。")
        return PackageList.post(self, request)


class DaqOwnReportFiles(ReportingView):
    def post(self, request, report_id, package_id):
        link = self.own_report(report_id)
        get_object_or_404(ProblemPackage, pk=package_id, defect=link.defect, created_by=request.user)
        return PackageFiles.post(self, request, pk=package_id)


class DaqOwnReportDownload(ReportingView, ImagePreview):
    def get(self, request, report_id, file_id, action=None):
        if action not in {None, "preview", "download"}:
            raise PermissionDenied("文件操作无效。")
        link = self.own_report(report_id)
        get_object_or_404(
            PackageFile,
            pk=file_id,
            package__defect=link.defect,
            created_by=request.user,
            package__created_by=request.user,
        )
        if action == "preview":
            return ImagePreview.get(self, request, pk=file_id)
        return FileDownload.get(self, request, pk=file_id)


def report_only_diagnostic_access(job):
    if job.mode != "auto" or job.result.get("trigger") not in {"daq_report", "materials_verified"}:
        return False
    link = SourceLink.objects.filter(
        defect=job.defect,
        source_system=SYSTEM,
        record_type=TYPE,
        created_by_id=job.created_by_id,
        project__archived_at__isnull=True,
        project__deleted_at__isnull=True,
        project__workspace__deleted_at__isnull=True,
    ).first()
    if not link:
        return False
    record = signed_record(link)
    if not record or record.get("authorityMode") != "report_only":
        return False
    return bool(record.get("reporter"))
