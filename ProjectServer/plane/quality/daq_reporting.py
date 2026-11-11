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
from . import platform
from .identity import PlatformBridgeAuthentication
from .models import DefectEvent, PlatformAccount, SourceLink, ProblemPackage, PackageFile
from .daq_incidents import DaqIncidents, DaqIncidentSession, IncidentInput, signed_record, receipt, TYPE, SYSTEM
from .sources import PackageList
from .attachments import PackageFiles, FileDownload, ImagePreview
from .views import QualityPagination


def verify_collector(source, external_actor):
    person = platform.fetch(source, f"/internal/issue-users/{external_actor}")
    if (
        not isinstance(person, dict)
        or person.get("id") != external_actor
        or person.get("active") is not True
        or person.get("role") != "Collector"
    ):
        raise AuthenticationFailed("来源账号未授予有效数采员职责。")
    return person


def verify_report_source(source, external_actor, external_project, task=None):
    verify_collector(source, external_actor)
    if not PlatformAccount.objects.filter(
        source_instance=source,
        external_user_id=external_actor,
        active=True,
        user__is_active=True,
        user__is_bot=False,
    ).exists():
        raise PermissionDenied("项目平台账号已停用。")
    permissions = platform.fetch(source, f"/internal/issue-permissions/users/{external_actor}")
    projects = permissions.get("projects") if isinstance(permissions, dict) else None
    if not isinstance(projects, list):
        raise platform.PlatformUnavailable()
    if not any(
        isinstance(row, dict) and type(row.get("id")) is int and row["id"] == external_project for row in projects
    ):
        raise PermissionDenied("数据平台项目权限已撤销。")
    context = {"projectId": external_project, "taskId": None, "sourceSessionId": None, "dataPackageId": None}
    if task is not None:
        context = platform.fetch(source, f"/internal/issue-integration/tasks/{task}/context")
        if (
            not isinstance(context, dict)
            or type(context.get("taskId")) is not int
            or context["taskId"] != task
            or type(context.get("projectId")) is not int
            or context["projectId"] != external_project
        ):
            raise PermissionDenied("来源任务不属于当前授权项目。")
    return context


class DaqReportingAuthentication(PlatformBridgeAuthentication):
    @transaction.atomic
    def authenticate(self, request):
        verified = self.verified_principal(request)
        if verified is None:
            return None
        config, external_actor = verified
        source = config["source_instance"]
        person = verify_collector(source, external_actor)
        account = (
            PlatformAccount.objects.select_related("user")
            .filter(source_instance=source, external_user_id=external_actor)
            .first()
        )
        if account:
            if not account.active or not account.user.is_active or account.user.is_bot:
                raise AuthenticationFailed("项目平台账号已停用。")
            user = account.user
        else:
            from .data_accounts import authority_config, link_account

            source_config = authority_config(source)
            if (
                not isinstance(person.get("username"), str)
                or not person["username"].strip()
                or len(person["username"]) > 128
            ):
                raise AuthenticationFailed("来源账号无效。")
            user = link_account(source, person, source_config).user
        return user, {"source_instance": source, "external_user_id": external_actor, "daq_report_only": True}


class ReportingView(BaseAPIView):
    authentication_classes = [DaqReportingAuthentication]
    permission_classes = [IsAuthenticated]

    def bind_project(self, project):
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
        data = record["payload"]
        verify_report_source(
            link.source_instance, record["externalActor"], data["platformProjectId"], data.get("platformTaskId")
        )
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
            Project.objects.filter(archived_at__isnull=True, workspace__deleted_at__isnull=True)
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
        # A count must respect current source permissions. Check the account in
        # authentication, fetch its projects once, and check each distinct task
        # once per request; never cache a grant across requests.
        permissions = platform.fetch(
            request.auth["source_instance"], f"/internal/issue-permissions/users/{request.auth['external_user_id']}"
        )
        projects = permissions.get("projects") if isinstance(permissions, dict) else None
        if not isinstance(projects, list):
            raise platform.PlatformUnavailable()
        allowed_projects = {row["id"] for row in projects if isinstance(row, dict) and type(row.get("id")) is int}
        task_contexts = {}
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
            if data["platformProjectId"] not in allowed_projects:
                continue
            task = data.get("platformTaskId")
            if task is not None:
                if task not in task_contexts:
                    try:
                        task_contexts[task] = platform.fetch(
                            link.source_instance, f"/internal/issue-integration/tasks/{task}/context"
                        )
                    except (AuthenticationFailed, PermissionDenied):
                        task_contexts[task] = None
                context = task_contexts[task]
                if (
                    not isinstance(context, dict)
                    or type(context.get("taskId")) is not int
                    or context["taskId"] != task
                    or type(context.get("projectId")) is not int
                    or context["projectId"] != data["platformProjectId"]
                ):
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

    timeline = [
        {
            "id": "created:" + str(defect.id),
            "actor": actor_name(defect.created_by),
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


class DaqOwnReportSession(ReportingView):
    def post(self, request, report_id):
        link = self.own_report(report_id)
        return DaqIncidentSession.post(self, request, pk=link.defect_id)


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
    try:
        verify_report_source(
            link.source_instance,
            record["externalActor"],
            record["payload"]["platformProjectId"],
            record["payload"].get("platformTaskId"),
        )
    except (AuthenticationFailed, PermissionDenied, platform.PlatformUnavailable):
        return False
    return True
