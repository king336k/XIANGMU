# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.db.models import F, Prefetch, Q, Exists, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.db.models import Issue, Project, ProjectMember, WorkspaceMember
from .models import CaseRevision, Defect, DefectEvent, PlanItem, TestCase, TestExecution, TestPlan, TestSuite
from .permissions import (
    roles_for,
    has_role,
    ROLE_NAMES,
    capable,
    permission_for,
    role_for,
    strict,
    require_assignee,
    is_administrator,
    capabilities_for,
)
from .serializers import (
    CaseInput,
    CaseSerializer,
    DefectInput,
    DefectSerializer,
    ExecutionInput,
    ExecutionSerializer,
    PlanInput,
    PlanSerializer,
    RevisionSerializer,
    plan_summary,
)


class Conflict(APIException):
    status_code = 409
    default_detail = "数据已变更，请刷新后重试。"


class QualityPermission(BasePermission):
    message = "您没有此项目的操作权限。"

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if is_administrator(request.user):
            return Project.objects.filter(
                pk=view.project_id,
                workspace__slug=view.workspace_slug,
                archived_at__isnull=True,
                workspace__deleted_at__isnull=True,
            ).exists()
        if not WorkspaceMember.objects.filter(
            workspace__slug=view.workspace_slug, member=request.user, is_active=True
        ).exists():
            return False
        if (
            request.method not in SAFE_METHODS
            and not WorkspaceMember.objects.filter(
                workspace__slug=view.workspace_slug, member=request.user, is_active=True, role__gte=15
            ).exists()
        ):
            return False
        roles = [5, 15, 20] if request.method in SAFE_METHODS else [15, 20]
        allowed = ProjectMember.objects.filter(
            workspace__slug=view.workspace_slug,
            project_id=view.project_id,
            project__archived_at__isnull=True,
            member=request.user,
            role__in=roles,
            is_active=True,
        ).exists()
        if allowed and request.method not in SAFE_METHODS:
            if type(view).__name__ == "CaseList" and request.method == "POST":
                return True
            return capable(view.project_id, request.user.id, permission_for(view, request))
        return allowed


class QualityPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "per_page"
    max_page_size = 100


class QualityView(BaseAPIView):
    permission_classes = [QualityPermission]

    def project(self):
        return get_object_or_404(
            Project, id=self.project_id, workspace__slug=self.workspace_slug, archived_at__isnull=True
        )

    def obj(self, model, pk, **filters):
        return get_object_or_404(model, pk=pk, project_id=self.project_id, **filters)

    def validate_issue(self, pk):
        if pk and not Issue.objects.filter(id=pk, project_id=self.project_id).exists():
            raise ValidationError({"error": "关联工作项必须属于当前项目。"})

    def validate_assignee(self, pk):
        if (
            pk
            and not ProjectMember.objects.filter(
                project_id=self.project_id,
                member_id=pk,
                member__is_active=True,
                is_active=True,
                role__gte=15,
                member__member_workspace__workspace__slug=self.workspace_slug,
                member__member_workspace__is_active=True,
                member__member_workspace__role__gte=15,
            ).exists()
        ):
            raise ValidationError({"error": "执行人必须是当前项目的有效成员。"})

    def listing(self, queryset, serializer):
        from .filters import filter_records

        queryset = filter_records(queryset, self.request.query_params, self.request.user)
        paginator = QualityPagination()
        items = paginator.paginate_queryset(queryset, self.request)
        from .numbering import preload

        preload(items)
        return paginator.get_paginated_response(serializer(items, many=True).data)

    def input(self, serializer, partial=False):
        data = serializer(data=self.request.data, partial=partial)
        data.is_valid(raise_exception=True)
        return data.validated_data


def add_revision(case, actor):
    snapshot = {key: getattr(case, key) for key in ["title", "module", "priority", "preconditions", "steps"]}
    snapshot["requirement_id"] = str(case.requirement_id) if case.requirement_id else None
    return CaseRevision.objects.create(
        case=case,
        project=case.project,
        title=case.title,
        version=case.version,
        snapshot=snapshot,
        created_by=actor,
    )


class CaseList(QualityView):
    def get(self, request, **kwargs):
        qs = TestCase.objects.filter(project=self.project()).select_related("requirement")
        return self.listing(qs, CaseSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(CaseInput)
        data.pop("expected_version", None)
        self.validate_issue(data.get("requirement_id"))
        case = TestCase.objects.create(project=self.project(), created_by=request.user, **data)
        add_revision(case, request.user)
        return Response(CaseSerializer(case).data, status=201)


class CaseDetail(QualityView):
    def get(self, request, pk, **kwargs):
        case = self.obj(TestCase, pk)
        return Response(
            {**CaseSerializer(case).data, "revisions": RevisionSerializer(case.revisions.all(), many=True).data}
        )

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(CaseInput, partial=True)
        expected = data.pop("expected_version", None)
        case = get_object_or_404(TestCase.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if case.archived_at or case.trashed_at:
            raise Conflict("用例已归档，请先恢复后再编辑。")
        if expected is None:
            raise ValidationError({"expected_version": "请提交当前用例版本。"})
        if expected != case.version:
            raise Conflict()
        self.validate_issue(data.get("requirement_id"))
        if data:
            for key, value in data.items():
                setattr(case, key, value)
            case.version += 1
            case.save()
            add_revision(case, request.user)
        return Response(CaseSerializer(case).data)


def plan_queryset():
    executions = (
        TestExecution.objects.select_related("created_by", "item__revision", "item__plan")
        .filter(
            Q(item__plan__managed=False, item__plan__defect_verification__isnull=True)
            | Q(round_no=F("item__plan__round_no"))
        )
        .order_by("item_id", "-created_at", "-id")
        .distinct("item_id")
    )
    items = PlanItem.objects.select_related("revision", "case").prefetch_related(
        Prefetch("executions", queryset=executions, to_attr="latest_results")
    )
    return TestPlan.objects.select_related(
        "assignee", "data_regression__binding", "defect_verification__defect"
    ).prefetch_related(Prefetch("items", queryset=items), "workflow_events__created_by")


class PlanList(QualityView):
    def get(self, request, **kwargs):
        project = self.project()
        qs = plan_queryset().filter(project=project)
        if request.query_params.get("current_only") == "true":
            qs = qs.filter(pk__in=current_plans(project).values("pk"))
        return self.listing(qs, PlanSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(PlanInput)
        suite_id = data.pop("suite_id", None)
        case_ids = data.pop("case_ids", [])
        if bool(suite_id) == bool(case_ids):
            raise ValidationError({"case_ids": "请选择用例或一个已发布套件，不能同时选择。"})
        suite = (
            self.obj(TestSuite, suite_id, published=True, archived_at__isnull=True, trashed_at__isnull=True)
            if suite_id
            else None
        )
        ids = {item.case_id for item in suite.items.all()} if suite else set(case_ids)
        self.validate_assignee(data.get("assignee_id"))
        if data.get("managed") and data.get("assignee_id"):
            require_assignee(self, data["assignee_id"], "REGRESSION_TESTER")
            if (
                not (strict(self.project_id) and capable(self.project_id, request.user.id, "manage_test_plan"))
                and not ProjectMember.objects.filter(
                    project_id=self.project_id, member=request.user, is_active=True, role=20
                ).exists()
            ):
                raise ValidationError({"assignee_id": "请在测试计划中分派负责人，再调整受管测试。"})
        cases = list(
            TestCase.objects.select_for_update().filter(
                project_id=self.project_id, id__in=ids, archived_at__isnull=True, trashed_at__isnull=True
            )
        )
        if len(cases) != len(ids):
            raise ValidationError({"case_ids": "用例不存在或不属于当前项目。"})
        plan = TestPlan.objects.create(project=self.project(), created_by=request.user, **data)
        if plan.managed and plan.assignee_id:
            plan.status = "ready"
            plan.save(update_fields=["status"])
        for case in cases:
            revision = suite.items.get(case=case).revision if suite else case.revisions.get(version=case.version)
            PlanItem.objects.create(
                plan=plan, case=case, revision=revision, project=plan.project, created_by=request.user
            )
        return Response(PlanSerializer(plan_queryset().get(pk=plan.pk)).data, status=201)


class PlanDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(PlanSerializer(get_object_or_404(plan_queryset(), pk=pk, project_id=self.project_id)).data)


class ExecutionList(QualityView):
    def get(self, request, pk=None, **kwargs):
        project = self.project()
        qs = TestExecution.objects.filter(project=project).select_related("created_by", "item__revision", "item__plan")
        if request.query_params.get("current_only") == "true":
            latest = (
                TestExecution.objects.filter(project=project, item__plan__in=current_plans(project))
                .filter(
                    Q(item__plan__managed=False, item__plan__defect_verification__isnull=True)
                    | Q(round_no=F("item__plan__round_no"))
                )
                .order_by("item_id", "-created_at", "-id")
                .distinct("item_id")
                .values("pk")
            )
            qs = qs.filter(pk__in=Subquery(latest))
        if pk:
            self.obj(PlanItem, pk)
            qs = qs.filter(item_id=pk)
        return self.listing(qs, ExecutionSerializer)

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(ExecutionInput)
        from .defect_verification import lock_execution, validate_actual

        verification = lock_execution(pk, self.project_id, request.user)
        item = get_object_or_404(PlanItem.objects.select_for_update(), pk=pk, project_id=self.project_id)
        plan = TestPlan.objects.select_for_update().get(pk=item.plan_id)
        if verification:
            validate_actual(data, item.revision.snapshot["steps"])
        results = data["step_results"]
        if results and len(results) != len(item.revision.snapshot["steps"]):
            raise ValidationError({"step_results": "逐步结果数量必须与固定版本的步骤数一致。"})
        if data["result"] == "passed" and any(step["result"] != "passed" for step in results):
            raise ValidationError({"result": "存在未通过步骤，不能将整条用例标记通过。"})
        existing = TestExecution.objects.filter(item=item, request_id=data["request_id"]).first()
        if existing:
            if (
                any(getattr(existing, key) != value for key, value in data.items())
                or verification
                and existing.created_by_id != request.user.id
            ):
                raise Conflict("同一提交编号不能用于不同的执行结果。")
            return Response(ExecutionSerializer(existing).data)
        if plan.archived_at:
            raise Conflict("测试计划已归档，请先恢复。")
        if plan.managed:
            if plan.status != "running":
                raise Conflict("当前计划不在执行中，请先认领或恢复测试。")
            if plan.assignee_id != request.user.id and not has_role(self.project_id, request.user.id, "PLATFORM_ADMIN"):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("只有当前测试负责人可以提交执行结果。")
        if data["result"] == "passed":
            from .data_regression import validate_pass

            validate_pass(plan, data)
        from .test_resources import preflight, require_ready

        resource_snapshot = require_ready(plan) if data["result"] == "passed" else preflight(plan)
        execution = TestExecution.objects.create(
            item=item,
            project=item.project,
            created_by=request.user,
            round_no=plan.round_no,
            resource_snapshot=resource_snapshot,
            **data,
        )
        if verification:
            from .defect_verification import sync_plan, audit

            sync_plan(verification)
            audit(verification.defect, request.user, f"记录用例实测第{verification.round_no}轮：{execution.result}")
        return Response(ExecutionSerializer(execution).data, status=201)


def defect_queryset():
    return Defect.objects.select_related(
        "assignee",
        "module",
        "case",
        "daq_report",
        "repair_issue",
        "source_execution__item__revision",
        "source_execution__item__plan",
        "source_execution__created_by",
        "regression_execution__item__revision",
        "regression_execution__item__plan",
        "regression_execution__created_by",
    ).prefetch_related("events__created_by", "sources")


class ExecutionDefect(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(DefectInput, partial=True)
        execution = get_object_or_404(TestExecution.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if execution.result != "failed":
            raise ValidationError({"error": "只有失败的测试执行可以生成缺陷。"})
        existing = Defect.objects.filter(source_execution=execution).first()
        if existing:
            return Response(DefectSerializer(defect_queryset().get(pk=existing.pk)).data)
        allowed = {key: data[key] for key in ["title", "severity", "description", "assignee_id"] if key in data}
        self.validate_assignee(allowed.get("assignee_id"))
        if allowed.get("assignee_id"):
            if strict(self.project_id) and not capable(self.project_id, request.user.id, "manage_test"):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("缺陷负责人须由项目经理分派。")
            require_assignee(self, allowed["assignee_id"], "TECHNICIAN")
        allowed.setdefault("title", f"[测试失败] {execution.item.revision.title}"[:255])
        allowed.setdefault("description", f"实际结果：{execution.actual_result}\n证据：{execution.evidence}")
        defect = Defect.objects.create(
            case=execution.item.case,
            source_execution=execution,
            project=execution.project,
            affected_build=execution.item.plan.build,
            created_by=request.user,
            **allowed,
        )
        DefectEvent.objects.create(
            defect=defect, project=defect.project, status="open", note="由失败执行创建", created_by=request.user
        )
        from .notifications import defect_notice

        defect_notice(defect, request.user, "新缺陷已分派")
        return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data, status=201)


class DefectList(QualityView):
    def get(self, request, **kwargs):
        return self.listing(defect_queryset().filter(project=self.project()), DefectSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(DefectInput, partial=True)
        if not data.get("title"):
            raise ValidationError({"title": "请填写缺陷标题。"})
        if data.get("status", "open") != "open":
            raise ValidationError({"status": "新缺陷必须从待处理开始。"})
        data.pop("regression_execution_id", None)
        for key in ["expected_version", "verification_method", "verification_note", "verification_scope_reason"]:
            data.pop(key, None)
        if data.get("verification_scope", "auto") != "auto":
            raise ValidationError({"verification_scope": "请先建单，再由项目经理确认验证方式。"})
        if data.get("case_id"):
            self.obj(TestCase, data["case_id"])
        self.validate_issue(data.get("repair_issue_id"))
        self.validate_assignee(data.get("assignee_id"))
        if data.get("assignee_id"):
            if strict(self.project_id) and not capable(self.project_id, request.user.id, "manage_test"):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("缺陷负责人须由项目经理分派。")
            require_assignee(self, data["assignee_id"], "TECHNICIAN")
        defect = Defect.objects.create(project=self.project(), created_by=request.user, **data)
        DefectEvent.objects.create(
            defect=defect, project=defect.project, status="open", note="手工提交缺陷", created_by=request.user
        )
        from .notifications import defect_notice

        defect_notice(defect, request.user, "新缺陷已分派")
        return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data, status=201)


class DefectDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(DefectSerializer(get_object_or_404(defect_queryset(), pk=pk, project_id=self.project_id)).data)

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(DefectInput, partial=True)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        from .defect_verification import guard_legacy

        guard_legacy(defect, data)
        if defect.archived_at:
            raise Conflict("缺陷已归档，请先恢复后再处理。")
        expected = data.pop("expected_version", None)
        if expected is not None and expected != defect.edit_version:
            raise Conflict()
        from .verification_scope import validate_scope_change

        scope_note = validate_scope_change(self, defect, data)
        self.validate_issue(data.get("repair_issue_id"))
        self.validate_assignee(data.get("assignee_id"))
        if data.get("case_id"):
            self.obj(TestCase, data["case_id"])
        if defect.source_execution_id and "case_id" in data and data["case_id"] != defect.case_id:
            raise ValidationError({"case_id": "测试产生的缺陷不能改变来源用例。"})
        if (
            not strict(self.project_id)
            and not is_administrator(request.user)
            and not ProjectMember.objects.filter(
                project_id=self.project_id, member=request.user, role=20, is_active=True
            ).exists()
            and defect.assignee_id != request.user.id
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("只有当前处理负责人或项目经理可以修改缺陷。")
        if strict(self.project_id):
            if (
                has_role(self.project_id, request.user.id, "TECHNICIAN")
                and not has_role(self.project_id, request.user.id, "PROJECT_MANAGER")
                and (
                    defect.assignee_id != request.user.id
                    or data.get("assignee_id", defect.assignee_id) != defect.assignee_id
                    or data.get("status") == "closed"
                )
            ):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("只有当前技术负责人可以处理缺陷，分派与关闭由项目经理执行。")
            if data.get("assignee_id"):
                require_assignee(self, data["assignee_id"], "TECHNICIAN")
        if defect.assignee_id and "assignee_id" in data and data["assignee_id"] != defect.assignee_id:
            raise Conflict("已有负责人需通过交接确认后切换，请使用“转派并交接”。")
        if defect.pending_assignee_id and "assignee_id" in data and data["assignee_id"] != defect.assignee_id:
            raise Conflict("已有待确认的交接，请先完成或取消交接。")
        verification_method = data.pop("verification_method", "regression")
        verification_note = data.pop("verification_note", "")
        previous_assignee = defect.assignee_id
        previous_severity = defect.severity
        old_status = defect.status
        new_status = data.get("status", old_status)
        allowed = {
            "open": {"open", "in_progress", "resolved"},
            "in_progress": {"open", "in_progress", "resolved"},
            "resolved": {"open", "resolved", "closed"},
            "closed": {"closed", "open"},
        }
        if new_status not in allowed[old_status]:
            raise ValidationError({"status": "请先修复，再完成回归验证。"})
        if old_status == "closed" and new_status != "open" and data:
            raise ValidationError({"status": "已关闭缺陷请先重开再修改。"})
        regression_id = data.pop("regression_execution_id", None)
        if new_status == "resolved" and not data.get("fixed_build", defect.fixed_build):
            raise ValidationError({"fixed_build": "请填写修复版本。"})
        if new_status == "closed":
            from .verification_scope import requires_data_regression

            if requires_data_regression(defect):
                raise ValidationError(
                    {"status": "此缺陷需完成数据回归与经理确认后关闭；普通功能问题可先由经理调整验证方式。"}
                )
            if data.get("fixed_build", defect.fixed_build) != defect.fixed_build:
                raise ValidationError({"fixed_build": "关闭时不能变更修复版本，请先保存修复信息并重新回归。"})
            if data.get("case_id", defect.case_id) != defect.case_id:
                raise ValidationError({"case_id": "关闭时不能变更验证用例，请先保存并重新回归。"})
            if verification_method == "manual":
                manager = (
                    capable(self.project_id, request.user.id, "manage_test")
                    if strict(self.project_id)
                    else ProjectMember.objects.filter(
                        project_id=self.project_id, member=request.user, is_active=True, role=20
                    ).exists()
                )
                if not manager:
                    from rest_framework.exceptions import PermissionDenied

                    raise PermissionDenied("人工验证关闭由项目经理确认。")
                if (
                    old_status != "resolved"
                    or not verification_note.strip()
                    or not DefectSerializer(defect).data["manual_verification_allowed"]
                ):
                    raise ValidationError(
                        {
                            "verification_note": (
                                "功能问题未关联用例时，须填写验证过程与结果；数据问题及已有用例的缺陷须走对应证据回归。"
                            )
                        }
                    )
                defect.regression_execution = None
            else:
                regression = self.obj(TestExecution, regression_id) if regression_id else None
                if (
                    old_status != "resolved"
                    or regression is None
                    or regression.result != "passed"
                    or defect.case_id is None
                    or regression.item.case_id != defect.case_id
                    or regression.item.plan.build != defect.fixed_build
                    or defect.resolved_at is None
                    or regression.created_at <= defect.resolved_at
                ):
                    raise ValidationError(
                        {"regression_execution_id": "关闭缺陷需要本次修复之后、同一用例的新通过执行。"}
                    )
                defect.regression_execution = regression
        if new_status == "resolved" and (
            old_status != "resolved"
            or data.get("fixed_build", defect.fixed_build) != defect.fixed_build
            or data.get("case_id", defect.case_id) != defect.case_id
        ):
            defect.resolved_at = timezone.now()
        if new_status in {"open", "in_progress"} and old_status == "closed":
            defect.resolution_kind = "fixed"
            defect.duplicate_of = None
            defect.defer_until = None
        if new_status == "in_progress" and defect.resolution_kind == "deferred":
            defect.resolution_kind = "fixed"
            defect.defer_until = None
        if new_status == "open" and old_status != "open":
            defect.resolved_at = None
            defect.regression_execution = None
            from .data_regression import invalidate_knowledge

            invalidate_knowledge(defect, request.user)
        for key, value in data.items():
            setattr(defect, key, value)
        if "severity" in data:
            defect.severity_origin = "manual" if defect.severity else "pending"
            defect.severity_reason = "人工调整严重程度。" if defect.severity else "等待下次诊断评估。"
            defect.severity_job = None
        if "assignee_id" in data and data["assignee_id"] != previous_assignee:
            defect.assignment_origin = "manual"
            defect.assignment_reason = "人工选择负责人。"
        defect.edit_version += 1
        defect.save()
        from .defect_verification import latest, sync_plan

        verification = latest(defect)
        if verification:
            sync_plan(verification)
        if old_status != "closed" and new_status == "closed":
            from .data_regression import create_functional_knowledge

            create_functional_knowledge(defect, request.user, verification_note)
        if data:
            DefectEvent.objects.create(
                defect=defect,
                project=defect.project,
                previous_status=old_status,
                status=new_status,
                note=(
                    f"人工验证关闭（{defect.fixed_build}）：{verification_note}"
                    if new_status == "closed" and verification_method == "manual"
                    else scope_note
                    or (
                        f"人工调整严重程度：{previous_severity or '待评估'} → {defect.severity or '待评估'}"
                        if "severity" in data else data.get("resolution", "更新缺陷")
                    )
                ),
                created_by=request.user,
            )
        from .notifications import defect_notice

        if data:
            defect_notice(defect, request.user, "缺陷处理已更新", [previous_assignee])
        return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)


class DefectReassignPermission(QualityPermission):
    def has_permission(self, request, view):
        from .permissions import writable_member

        return bool(
            request.user.is_authenticated
            and (
                is_administrator(request.user) or writable_member(view.project_id, request.user.id, view.workspace_slug)
            )
        )


class DefectReassign(QualityView):
    permission_classes = [DefectReassignPermission]

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        from rest_framework import serializers
        from rest_framework.exceptions import PermissionDenied
        from .module_owners import StrictInput, eligible_technician, module_record
        from .permissions import writable_member
        from .data_regression import manager

        class ReassignInput(StrictInput):
            expected_version = serializers.IntegerField(min_value=1)
            assignee_id = serializers.UUIDField(allow_null=True)
            reason = serializers.CharField(max_length=2000)
            module_key = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,63}$", required=False, allow_null=True)

        data = self.input(ReassignInput)
        defect = get_object_or_404(
            Defect.objects.select_for_update(),
            pk=pk,
            project_id=self.project_id,
            project__workspace__slug=self.workspace_slug,
            project__archived_at__isnull=True,
        )
        administrator = is_administrator(request.user)
        allowed = administrator or (
            writable_member(self.project_id, request.user.id, self.workspace_slug)
            and (defect.assignee_id == request.user.id or manager(self.project_id, request.user))
        )
        if not allowed:
            raise PermissionDenied("只有当前负责人、项目经理或管理员可以改派。")
        if defect.edit_version != data["expected_version"]:
            raise Conflict()
        if defect.archived_at or defect.status == "closed" or defect.pending_assignee_id:
            raise Conflict("缺陷已结束、归档或存在待确认交接，请先处理当前状态。")
        target = data["assignee_id"]
        module = defect.module
        if "module_key" in data:
            module = module_record(data["module_key"]) if data["module_key"] else None
        from plane.db.models import User
        from .models import PlatformAccount

        local_human = target and User.objects.filter(pk=target, is_active=True, is_bot=False).exists()
        local_human = local_human and not PlatformAccount.objects.filter(user_id=target).exists()
        triage_target = (
            module is None
            and local_human
            and (is_administrator(target) or has_role(self.project_id, target, "PROJECT_MANAGER"))
        )
        if target and not triage_target and not eligible_technician(defect.project, target):
            raise ValidationError({"assignee_id": "请选择有效技术员；模块未确认时也可交项目经理或管理员分诊。"})
        previous = defect.assignee
        if (
            defect.assignee_id == target
            and defect.module_id == getattr(module, "key", None)
            and defect.assignment_origin == "manual"
        ):
            return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)
        defect.assignee_id = target
        defect.module = module
        defect.assignment_origin = "manual"
        defect.assignment_reason = data["reason"]
        defect.edit_version += 1
        defect.save()
        current_name = defect.assignee.display_name or defect.assignee.username if target else "未指派"
        previous_name = previous.display_name or previous.username if previous else "未指派"
        DefectEvent.objects.create(
            project=defect.project,
            defect=defect,
            created_by=request.user,
            previous_status=defect.status,
            status=defect.status,
            note=(
                f"人工改派：{previous_name} → {current_name}；"
                f"模块：{module.name if module else '未确认'}；原因：{data['reason']}"
            ),
        )
        from .notifications import defect_notice

        defect_notice(defect, request.user, "缺陷负责人已改派", [previous.id] if previous else [])
        return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)


class DefectReportEdit(QualityView):
    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        from rest_framework.exceptions import PermissionDenied

        if set(request.data) - {"title", "description", "affected_build", "expected_version"}:
            raise ValidationError({"error": "这里只能补充上报标题、现象和影响版本。"})
        data = self.input(DefectInput, partial=True)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if defect.created_by_id != request.user.id:
            raise PermissionDenied("只能补充本人上报的缺陷信息。")
        if defect.archived_at or defect.status == "closed":
            raise Conflict("缺陷已关闭或归档，请联系项目经理处理。")
        if data.pop("expected_version", None) != defect.edit_version:
            raise Conflict()
        if data:
            previous = {key: getattr(defect, key) for key in data}
            for key, value in data.items():
                setattr(defect, key, value)
            defect.edit_version += 1
            defect.save()
            import json

            DefectEvent.objects.create(
                project=defect.project,
                defect=defect,
                created_by=request.user,
                previous_status=defect.status,
                status=defect.status,
                note="补充上报信息；修改前：" + json.dumps(previous, ensure_ascii=False),
            )
        return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)


class QualityContext(QualityView):
    def get(self, request, **kwargs):
        project = self.project()
        members = ProjectMember.objects.filter(
            project=project,
            is_active=True,
            member__is_active=True,
            member__member_workspace__workspace=project.workspace,
            member__member_workspace__is_active=True,
        ).select_related("member")
        issues = Issue.objects.filter(project=project).order_by("-created_at")[:200]
        duties = roles_for(project.id, request.user.id)
        administrator = is_administrator(request.user)
        if administrator:
            duties.add("PLATFORM_ADMIN")
        capabilities = capabilities_for(project.id, request.user.id, duties)
        if administrator:
            capabilities = {key: True for key in capabilities}
        member_rows = []
        for member in members:
            member_duties = roles_for(project.id, member.member_id)
            member_rows.append(
                {
                    "id": member.member_id,
                    "name": member.member.display_name or member.member.first_name or "成员",
                    "role": member.role,
                    "business_role": "PLATFORM_ADMIN"
                    if "PLATFORM_ADMIN" in member_duties
                    else next(iter(sorted(member_duties)), None),
                    "business_roles": sorted(member_duties),
                    "is_administrator": "PLATFORM_ADMIN" in member_duties,
                }
            )
        return Response(
            {
                "business_role": role_for(project.id, request.user.id),
                "is_administrator": administrator,
                "can_manage_administrators": administrator,
                "business_roles": sorted(duties),
                "business_role_name": "、".join(ROLE_NAMES[role] for role in sorted(duties)) or "项目成员",
                "business_roles_enabled": strict(project.id),
                "capabilities": capabilities,
                "project_name": project.name,
                "identifier": project.identifier,
                "work_item_options_url": (
                    f"/api/workspaces/{project.workspace.slug}/projects/{project.id}/quality/work-item-options/"
                ),
                "can_write": administrator
                or ProjectMember.objects.filter(
                    project=project, member=request.user, is_active=True, role__gte=15
                ).exists()
                and WorkspaceMember.objects.filter(
                    workspace=project.workspace, member=request.user, is_active=True, role__gte=15
                ).exists(),
                "user_id": request.user.id,
                "can_review_knowledge": capabilities["knowledge_review"],
                "can_configure_model": administrator
                and ProjectMember.objects.filter(
                    project=project, member=request.user, is_active=True, role__gte=15
                ).exists()
                and WorkspaceMember.objects.filter(
                    workspace=project.workspace, member=request.user, is_active=True, role__gte=15
                ).exists(),
                "is_manager": administrator
                or (strict(project.id) and capable(project.id, request.user.id, "manage_test"))
                or ProjectMember.objects.filter(project=project, member=request.user, is_active=True, role=20).exists()
                and not strict(project.id)
                and WorkspaceMember.objects.filter(
                    workspace=project.workspace, member=request.user, is_active=True, role__gte=15
                ).exists(),
                "members": member_rows,
                "issues": [{"id": i.id, "name": i.name, "sequence_id": i.sequence_id} for i in issues],
            }
        )


class QualityReport(QualityView):
    def get(self, request, **kwargs):
        return Response(quality_report(self.project()))


def quality_report(project):
    plans = list(plan_queryset().filter(pk__in=current_plans(project).values("pk")))
    totals = {
        key: 0 for key in ["passed", "failed", "blocked", "inconclusive", "skipped", "pending", "total", "executed"]
    }
    for plan in plans:
        if getattr(plan, "defect_verification", None) and plan.defect_verification.mode == "manual":
            continue
        summary = plan_summary(plan)
        for key in totals:
            totals[key] += summary[key]
    totals["execution_rate"] = round(totals["executed"] * 100 / totals["total"], 1) if totals["total"] else 0
    totals["pass_rate"] = round(totals["passed"] * 100 / totals["executed"], 1) if totals["executed"] else 0
    cases = TestCase.objects.filter(project=project, archived_at__isnull=True, trashed_at__isnull=True)
    from .models import DefectVerificationResult

    return {
        "summary": totals,
        "manual_verification": manual_verification_summary(project),
        "manual_execution_count": DefectVerificationResult.objects.filter(project=project).count(),
        "case_count": cases.count(),
        "plan_count": len(plans),
        "historical_plan_count": TestPlan.objects.filter(project=project).count(),
        "execution_count": TestExecution.objects.filter(project=project).count(),
        "open_defects": Defect.objects.filter(project=project, archived_at__isnull=True)
        .exclude(status="closed")
        .count(),
        "closed_defects": Defect.objects.filter(project=project, archived_at__isnull=True, status="closed").count(),
        "requirement_linked_cases": cases.filter(requirement__isnull=False).count(),
        "definitions": {
            "scope": (
                "当前有效、未归档且未取消的计划条目，每条只取本轮最新执行；"
                "缺陷验证仅计最新且修复版本、修复时间、用例版本仍有效的轮次。人工验证独立计轮，不计入用例条目。"
            ),
            "history": (
                "execution_count保留全部历史用例执行，manual_execution_count保留全部人工实测记录，"
                "historical_plan_count保留全部历史计划；归档与退回不会删除历史。"
            ),
            "manual_verification": "当前有效人工验证轮次，每轮取最新实际结果；total单位为验证轮次，不是用例数。",
            "execution_rate": "已执行条目 / 全部条目（阻塞、无法判定、跳过计为已执行）",
            "pass_rate": "通过条目 / 已执行条目（阻塞、无法判定、跳过计入分母）",
        },
    }


def current_verifications(project):
    from .models import DefectVerification

    latest_round = (
        DefectVerification.objects.filter(defect_id=OuterRef("defect_id")).order_by("-round_no").values("round_no")[:1]
    )
    stale_cases = PlanItem.objects.filter(plan_id=OuterRef("plan_id")).exclude(revision__version=F("case__version"))
    return (
        DefectVerification.objects.filter(project=project)
        .annotate(latest_round=Subquery(latest_round), stale_cases=Exists(stale_cases))
        .filter(
            round_no=F("latest_round"),
            status__in=["testing", "review", "accepted"],
            defect__archived_at__isnull=True,
            defect__status__in=["resolved", "closed"],
            fixed_build=F("defect__fixed_build"),
            defect__resolved_at__isnull=False,
            stale_cases=False,
        )
        .filter(Q(resolved_at=F("defect__resolved_at")) | Q(resolved_at__isnull=True))
        .filter(Q(mode="manual") | Q(plan__build=F("fixed_build"), plan__round_no=F("round_no")))
    )


def current_plans(project):
    return (
        TestPlan.objects.filter(project=project, archived_at__isnull=True)
        .exclude(status="cancelled")
        .filter(Q(defect_verification__isnull=True) | Q(defect_verification__in=current_verifications(project)))
    )


def manual_verification_summary(project):
    counts = {key: 0 for key in ["passed", "failed", "blocked", "inconclusive", "skipped", "pending"]}
    accepted = 0
    for row in current_verifications(project).filter(mode="manual").prefetch_related("manual_results"):
        execution = next(iter(row.manual_results.all()), None)
        counts[execution.result if execution else "pending"] += 1
        accepted += int(row.status == "accepted")
    total = sum(counts.values())
    executed = total - counts["pending"]
    return {
        **counts,
        "total": total,
        "executed": executed,
        "accepted": accepted,
        "execution_rate": round(executed * 100 / total, 1) if total else 0,
        "pass_rate": round(counts["passed"] * 100 / executed, 1) if executed else 0,
    }
