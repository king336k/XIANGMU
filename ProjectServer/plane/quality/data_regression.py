# SPDX-License-Identifier: AGPL-3.0-only
"""Fresh DAQ data verification is an extension of native managed test plans."""

import json
from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import ProjectMember
from .models import (
    DataRegression,
    DataEvidence,
    Defect,
    DefectEvent,
    DaqReport,
    PlatformProject,
    SolutionRevision,
    TestCase,
    TestPlan,
    PlanItem,
    PlanEvent,
)
from .permissions import capable, strict
from .serializers import PlanSerializer, StepInput
from .views import QualityView, Conflict, add_revision, plan_queryset
from . import platform


def manager(project_id, user):
    return (
        capable(project_id, user.id, "manage_test")
        if strict(project_id)
        else ProjectMember.objects.filter(project_id=project_id, member=user, role=20, is_active=True).exists()
    )


class RegressionInput(serializers.Serializer):
    solution_id = serializers.UUIDField()
    environment = serializers.CharField(max_length=255)
    test_target = serializers.CharField(max_length=4000, allow_blank=True, default="")
    verification_steps = StepInput(many=True, allow_empty=False, max_length=100, required=False)
    environment_details = serializers.JSONField(default=dict)

    def validate_environment_details(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("环境详情须为JSON对象。")
        pending = [(value, 1)]
        while pending:
            item, level = pending.pop()
            if level > 8:
                raise serializers.ValidationError("环境详情最多支持8层结构。")
            children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else []
            pending.extend((child, level + 1) for child in children if isinstance(child, (dict, list)))
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise serializers.ValidationError("环境详情须为有效JSON对象，不能包含非有限数值。")
        if len(encoded) > 20000:
            raise serializers.ValidationError("环境详情不能超过20000字符。")
        return value


class EvidenceInput(serializers.Serializer):
    source_session_id = serializers.CharField(max_length=255)


class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataEvidence
        fields = ["id", "round_no", "source_session_id", "package_id", "collected_at", "snapshot", "created_at"]


def information(regression):
    return {
        "id": str(regression.id),
        "defect_id": str(regression.defect_id),
        "solution_revision_id": str(regression.solution_revision_id),
        "fixed_build": regression.fixed_build,
        "request_snapshot": regression.request_snapshot,
        "round_started_at": regression.round_started_at,
        "evidence": EvidenceSerializer(regression.evidence.all(), many=True).data,
        "plan": PlanSerializer(plan_queryset().get(pk=regression.plan_id)).data,
    }


class DataRegressionList(QualityView):
    def get(self, request, pk, **kwargs):
        self.obj(Defect, pk)
        return Response(
            [information(row) for row in DataRegression.objects.filter(project_id=self.project_id, defect_id=pk)]
        )

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(RegressionInput)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if (
            not manager(self.project_id, request.user)
            and not (strict(self.project_id) and capable(self.project_id, request.user.id, "manage_test_plan"))
            and defect.assignee_id != request.user.id
        ):
            raise PermissionDenied("仅当前技术负责人或有测试管理权限的成员可发起数据回归。")
        from .verification_scope import requires_data_regression

        if not requires_data_regression(defect):
            raise Conflict("此缺陷使用功能验证，无需发起重新采集；请按测试用例或人工验证结果关闭。")
        if defect.status != "resolved" or not defect.fixed_build or not defect.resolved_at:
            raise Conflict("先保存修复版本与修复说明，再发起重新采集验证。")
        if (
            DataRegression.objects.filter(defect=defect)
            .exclude(plan__status__in=["completed", "cancelled", "failed"])
            .exists()
        ):
            raise Conflict("此缺陷已有进行中的数据回归，请继续当前计划。")
        revision = get_object_or_404(
            SolutionRevision.objects.select_for_update().select_related("solution"),
            solution_id=data["solution_id"],
            solution__defect=defect,
            solution__status="approved",
            version=F("solution__submitted_version"),
        )
        report = DaqReport.objects.select_related("binding").filter(defect=defect).first()
        if report:
            binding = report.binding
        else:
            from .daq_incidents import regression_binding

            binding = regression_binding(defect, request.user)
        if not binding.active:
            raise Conflict("原采集任务映射已停用，请核对来源。")
        started = timezone.now()
        approved_verification = revision.snapshot.get("verification") or "原异常不再出现，数据与日志符合验收要求"
        steps = data.get("verification_steps") or [
            {
                "action": "在修复版本重新采集，关联本轮新Session与数据包后检查",
                "expected": approved_verification,
            }
        ]
        request_snapshot = deepcopy(
            {
                "test_target": data["test_target"],
                "verification_steps": steps,
                "environment": data["environment"],
                "environment_details": data["environment_details"],
                "approved_verification": approved_verification,
            }
        )
        case = TestCase.objects.create(
            project=defect.project,
            created_by=request.user,
            title=f"重新采集验证：{defect.title}"[:255],
            module="采集数据回归",
            steps=steps,
            requirement=defect.repair_issue,
        )
        fixed = add_revision(case, request.user)
        fixed.snapshot["regression_request"] = request_snapshot
        fixed.save(update_fields=["snapshot"])
        plan = TestPlan.objects.create(
            project=defect.project,
            created_by=request.user,
            name=f"数据回归：{defect.title}"[:255],
            build=defect.fixed_build,
            environment=data["environment"],
            managed=True,
        )
        PlanItem.objects.create(project=defect.project, created_by=request.user, plan=plan, case=case, revision=fixed)
        row = DataRegression.objects.create(
            project=defect.project,
            created_by=request.user,
            plan=plan,
            defect=defect,
            solution_revision=revision,
            binding=binding,
            fixed_build=defect.fixed_build,
            resolved_at=defect.resolved_at,
            round_started_at=started,
            request_snapshot=request_snapshot,
        )
        return Response(information(row), status=201)


class DataEvidenceList(QualityView):
    def get(self, request, pk, **kwargs):
        row = get_object_or_404(DataRegression, plan_id=pk, project_id=self.project_id)
        return Response(EvidenceSerializer(row.evidence.all(), many=True).data)

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(EvidenceInput)
        plan = get_object_or_404(TestPlan.objects.select_for_update(), pk=pk, project_id=self.project_id)
        row = get_object_or_404(
            DataRegression.objects.select_for_update().select_related("binding", "defect"), plan=plan
        )
        from .permissions import has_role

        if plan.status != "running" or (
            plan.assignee_id != request.user.id and not has_role(self.project_id, request.user.id, "PLATFORM_ADMIN")
        ):
            raise PermissionDenied("请由当前测试负责人认领后关联新数据。")
        check_current(row, plan)
        context, collected = verified_context(row, data["source_session_id"])
        package = str(context["dataPackageId"])
        existing = row.evidence.filter(source_session_id=data["source_session_id"]).first()
        if existing:
            if (
                existing.round_no != plan.round_no
                or existing.package_id != package
                or existing.collected_at != collected
            ):
                raise Conflict("此来源已被其他轮次或不同数据使用，不能覆盖历史。")
            return Response(EvidenceSerializer(existing).data)
        if row.evidence.filter(package_id=package).exists():
            raise Conflict("此数据包已经关联过，不能重复用于新的验证。")
        evidence = DataEvidence.objects.create(
            project=plan.project,
            created_by=request.user,
            regression=row,
            round_no=plan.round_no,
            source_session_id=data["source_session_id"],
            package_id=package,
            collected_at=collected,
            snapshot={
                key: context.get(key)
                for key in ["projectId", "taskId", "sourceSessionId", "dataPackageId", "deviceName", "collectedAt"]
            },
        )
        PlanEvent.objects.create(
            project=plan.project,
            created_by=request.user,
            plan=plan,
            action="data_linked",
            previous_status=plan.status,
            status=plan.status,
            round_no=plan.round_no,
            note=f"关联本轮新采集数据：{data['source_session_id']} / {package}",
        )
        return Response(EvidenceSerializer(evidence).data, status=201)


def verified_context(row, session_id):
    from .daq_incidents import trusted_incident

    incident = trusted_incident(row.defect)
    binding = row.binding
    mappings = PlatformProject.objects.filter(
        project_id=row.project_id, source_instance=binding.source_instance, active=True
    )
    if binding.external_project_id:
        mappings = mappings.filter(external_project_id=binding.external_project_id)
    if mappings.count() != 1:
        raise Conflict("原采集任务的来源项目不明确，请先核对关联。")
    mapping = mappings.get()
    context = platform.fetch(
        binding.source_instance,
        f"/internal/issue-integration/tasks/{binding.platform_task_id}/context",
        {"sourceSessionId": session_id},
    )
    try:
        collected = parse_datetime(str(context.get("collectedAt", ""))) if isinstance(context, dict) else None
    except ValueError:
        collected = None
    if collected and timezone.is_naive(collected):
        try:
            zone = ZoneInfo(platform.configuration(binding.source_instance).get("timezone", "Asia/Shanghai"))
            collected = timezone.make_aware(collected, zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise platform.PlatformUnavailable()
    if (
        not isinstance(context, dict)
        or context.get("projectId") != mapping.external_project_id
        or context.get("taskId") != binding.platform_task_id
        or context.get("sourceSessionId") != session_id
        or not context.get("dataPackageId")
        or len(str(context.get("dataPackageId", ""))) > 255
        or str(context["dataPackageId"]) == binding.package_id
        or session_id == binding.source_record_id
        or not collected
        or (
            (incident is not None or "dataReady" in context)
            and (
                context.get("dataReady") is not True
                or context.get("dataPackageStatus")
                not in {
                    "PendingAnnotation",
                    "PendingReview",
                    "PendingManagerConfirmation",
                    "RecollectionRequired",
                    "ReviewPassed",
                    "ReviewFailed",
                }
            )
        )
        or collected < max(row.round_started_at, row.resolved_at)
        or collected > timezone.now() + timedelta(minutes=5)
    ):
        raise ValidationError(
            {
                "source_session_id": (
                    "请选择原任务中本轮送测后新采集、已完成处理的数据包；处理中、失败、旧数据或归属不符不能使用。"
                )
            }
        )
    return context, collected


def check_current(row, plan):
    if (
        row.defect.status != "resolved"
        or row.defect.fixed_build != row.fixed_build
        or row.defect.resolved_at != row.resolved_at
        or plan.build != row.fixed_build
        or not row.binding.active
    ):
        raise Conflict("修复信息或来源已变更，请重新发起数据回归，不能沿用旧验收。")


def validate_pass(plan, data):
    row = DataRegression.objects.select_related("defect", "binding").filter(plan=plan).first()
    if not row:
        return
    check_current(row, plan)
    if (
        not data.get("actual_result", "").strip()
        or not data.get("evidence", "").strip()
        or not row.evidence.filter(round_no=plan.round_no, collected_at__gte=row.round_started_at).exists()
    ):
        raise ValidationError({"evidence": "数据回归通过需要本轮新采集证据，以及实际检查结果和验证依据。"})


def transition(plan, action, actor, comment):
    row = (
        DataRegression.objects.select_for_update()
        .select_related("defect", "binding", "solution_revision__solution")
        .filter(plan=plan)
        .first()
    )
    if not row:
        if action == "submit":
            return_failed_functional_fixes(plan, actor)
        return
    if action == "cancel":
        return
    row.defect = Defect.objects.select_for_update().get(pk=row.defect_id)
    if row.defect.verification_rounds.exists():
        raise Conflict("此缺陷已配置验证流程，请从缺陷详情验收或退回。")
    check_current(row, plan)
    if action == "submit":
        from .serializers import plan_summary

        summary = plan_summary(plan_queryset().get(pk=plan.pk))
        if summary["failed"]:
            defect = row.defect
            defect.status, defect.resolved_at, defect.regression_execution = "open", None, None
            defect.edit_version += 1
            defect.save()
            DefectEvent.objects.create(
                project=plan.project,
                created_by=actor,
                defect=defect,
                previous_status="resolved",
                status="open",
                note=f"回归失败，返回技术负责人继续修复：{plan.name}",
            )
            return "failed"
    if action == "return":
        row.round_started_at = timezone.now()
        row.save(update_fields=["round_started_at"])
    if action == "approve":
        from .serializers import plan_summary

        snapshot = plan_queryset().get(pk=plan.pk)
        if (
            plan_summary(snapshot)["passed"] != plan_summary(snapshot)["total"]
            or not row.evidence.filter(round_no=plan.round_no, collected_at__gte=row.round_started_at).exists()
        ):
            raise ValidationError({"evidence": "本轮数据验证未通过或缺少新采集证据，不能关闭缺陷。"})
        if (
            row.solution_revision.solution.status != "approved"
            or row.solution_revision.version != row.solution_revision.solution.submitted_version
        ):
            raise Conflict("技术方案已变更，请核对新的审核与回归。")
        for evidence in row.evidence.filter(round_no=plan.round_no):
            current, collected = verified_context(row, evidence.source_session_id)
            if str(current["dataPackageId"]) != evidence.package_id or collected != evidence.collected_at:
                raise Conflict("已关联数据在平台上发生变更，请退回重新核对后验收。")
        defect = Defect.objects.select_for_update().get(pk=row.defect_id)
        defect.status = "closed"
        defect.edit_version += 1
        defect.regression_execution = snapshot.items.first().latest_results[0]
        defect.save()
        DefectEvent.objects.create(
            project=plan.project,
            created_by=actor,
            defect=defect,
            previous_status="resolved",
            status="closed",
            note=f"经理确认本轮新采集数据回归通过：{plan.name}。{comment}",
        )
        from plane.knowledge.models import Article

        Article.objects.create(
            project=plan.project,
            created_by=actor,
            source_issue=defect.repair_issue,
            source_defect=defect,
            source_regression=row,
            title=f"故障处理：{defect.title}"[:255],
            content=(
                f"现象：{defect.description}\n修复版本：{row.fixed_build}\n"
                f"方案：{row.solution_revision.snapshot.get('title', '')}\n"
                f"根因：{row.solution_revision.snapshot.get('root_cause', '')}\n"
                f"修复步骤：{row.solution_revision.snapshot.get('steps', '')}\n"
                f"验证方法：{row.solution_revision.snapshot.get('verification', '')}\n"
                f"风险：{row.solution_revision.snapshot.get('risk', '')}\n"
                f"回滚：{row.solution_revision.snapshot.get('rollback', '')}\n"
                "采集证据："
                + ", ".join(row.evidence.filter(round_no=plan.round_no).values_list("source_session_id", flat=True))
                + "\n"
                f"验证计划：{plan.id}\n结论：本轮新数据回归通过。"
            ),
            status="draft",
        )


def return_failed_functional_fixes(plan, actor):
    from .verification_scope import requires_data_regression

    snapshot = plan_queryset().get(pk=plan.pk)
    for item in snapshot.items.all():
        if not item.latest_results or item.latest_results[0].result != "failed":
            continue
        execution = item.latest_results[0]
        candidates = [
            defect
            for defect in Defect.objects.select_for_update()
            .filter(
                project_id=plan.project_id,
                case_id=item.case_id,
                fixed_build=plan.build,
                status="resolved",
                archived_at__isnull=True,
                resolved_at__lt=execution.created_at,
            )
            .order_by("id")
            if not requires_data_regression(defect) and not defect.verification_rounds.exists()
        ]
        # A general test plan has no explicit defect link. Never choose between ambiguous fixes.
        if len(candidates) != 1:
            continue
        defect = candidates[0]
        defect.status, defect.resolved_at, defect.regression_execution = "open", None, None
        defect.edit_version += 1
        defect.save()
        DefectEvent.objects.create(
            project=plan.project,
            created_by=actor,
            defect=defect,
            previous_status="resolved",
            status="open",
            note=f"功能回归失败，返回技术负责人继续修复：{plan.name}；验证记录：{execution.id}",
        )
        invalidate_knowledge(defect, actor)


def create_functional_knowledge(defect, actor, verification_note):
    from django.db.models import F
    from plane.knowledge.models import Article
    from .models import SolutionRevision

    revision = (
        SolutionRevision.objects.filter(
            solution__defect=defect,
            solution__status="approved",
            version=F("solution__submitted_version"),
        )
        .order_by("-created_at", "-id")
        .first()
    )
    lines = [f"现象：{defect.description}", f"修复版本：{defect.fixed_build}", f"处理结果：{defect.resolution}"]
    if revision:
        for key, label in [
            ("title", "方案"),
            ("root_cause", "根因"),
            ("steps", "修复步骤"),
            ("verification", "验证方法"),
            ("risk", "风险"),
            ("rollback", "回滚"),
        ]:
            value = revision.snapshot.get(key, "")
            if value:
                lines.append(f"{label}：{value}")
    if defect.regression_execution_id:
        execution = defect.regression_execution
        lines.extend(
            [
                f"验证计划：{execution.item.plan_id}",
                f"验证记录：{execution.id}",
                f"验证结果：{execution.actual_result}",
                f"验证依据：{execution.evidence}",
            ]
        )
    else:
        lines.append(f"功能验证结果：{verification_note}")
    return Article.objects.create(
        project=defect.project,
        created_by=actor,
        source_issue=defect.repair_issue,
        source_defect=defect,
        title=f"问题处理：{defect.title}"[:255],
        content="\n".join(lines),
        status="draft",
    )


def invalidate_knowledge(defect, actor):
    from plane.knowledge.models import Article, ArticleEvent

    for article in Article.objects.select_for_update().filter(source_defect=defect).exclude(status="offline"):
        article.status, article.publication_active = "offline", False
        article.edit_version += 1
        article.save()
        ArticleEvent.objects.create(
            project=defect.project,
            created_by=actor,
            article=article,
            action="source_reopened",
            version=article.edit_version,
            note="来源缺陷重开，暂时停止检索，重新整理审核后发布。",
        )
