# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
import json
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from .authorship import AuthoredRecordSerializer
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from django.db.models import Q
from .models import Defect, SavedReport, TestPlan, ReportConclusion
from .serializers import DefectSerializer, PlanSerializer, plan_summary
from .views import (
    Conflict,
    QualityView,
    defect_queryset,
    plan_queryset,
    quality_report,
    current_plans,
    current_verifications,
)


class ReportInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    plan_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    request_id = serializers.UUIDField()


class RenameInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    expected_version = serializers.IntegerField(min_value=1)


class ReportSerializer(AuthoredRecordSerializer):
    conclusion = serializers.SerializerMethodField()

    def get_conclusion(self, obj):
        row = getattr(obj, "conclusion", None)
        return conclusion_representation(row) if row else None

    class Meta:
        model = SavedReport
        fields = ["id", "name", "plan_id", "edit_version", "created_at", "snapshot", "conclusion"]


class ReportListSerializer(ReportSerializer):
    class Meta(ReportSerializer.Meta):
        fields = ["id", "name", "plan_id", "edit_version", "created_at"]


class ReportList(QualityView):
    def get(self, request, **kwargs):
        return self.listing(SavedReport.objects.filter(project=self.project()).defer("snapshot"), ReportListSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(ReportInput)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        fingerprint = hashlib.sha256(JSONRenderer().render(data)).hexdigest()
        existing = SavedReport.objects.filter(project=project, request_id=data["request_id"]).first()
        if existing:
            if existing.request_hash != fingerprint:
                raise Conflict("同一提交编号对应的报告参数不同。")
            return Response(ReportSerializer(existing).data)
        plan_id = data["plan_id"]
        if plan_id:
            self.obj(TestPlan, plan_id)
        list(TestPlan.objects.select_for_update().filter(project=project).order_by("id"))
        plans = plan_queryset().filter(project=project)
        if plan_id:
            plans = plans.filter(pk=plan_id)
        else:
            plans = plans.filter(pk__in=current_plans(project).values("pk"))
        snapshots = PlanSerializer(plans, many=True).data
        related = Defect.objects.filter(project=project, archived_at__isnull=True)
        if plan_id:
            plan = plans.get()
            summary = plan_summary(plan)
            related = (
                Defect.objects.filter(project=project)
                .filter(Q(source_execution__item__plan=plan) | Q(verification_rounds__plan=plan))
                .distinct()
            )
        else:
            overview = quality_report(project)
            summary = overview["summary"]
        manual_rows = []
        if not plan_id:
            for row in current_verifications(project).filter(mode="manual").prefetch_related("manual_results"):
                actual = next(iter(row.manual_results.all()), None)
                manual_rows.append(
                    {
                        "id": str(row.id),
                        "defect_id": str(row.defect_id),
                        "round_no": row.round_no,
                        "fixed_build": row.fixed_build,
                        "environment": row.environment,
                        "steps": row.steps,
                        "status": row.status,
                        "latest_result": (
                            {
                                "id": str(actual.id),
                                "result": actual.result,
                                "actual_result": actual.actual_result,
                                "evidence": actual.evidence,
                                "step_results": actual.step_results,
                                "created_at": actual.created_at,
                                "created_by_id": str(actual.created_by_id) if actual.created_by_id else None,
                            }
                            if actual
                            else None
                        ),
                    }
                )
        snapshot = {
            "schema_version": 2,
            "scope": "historical_plan" if plan_id else "current_project",
            "project_name": project.name,
            "summary": summary,
            "manual_verification": overview["manual_verification"] if not plan_id else None,
            "manual_validations": manual_rows,
            "manual_execution_count": overview["manual_execution_count"] if not plan_id else 0,
            "plans": snapshots,
            "defects": DefectSerializer(defect_queryset().filter(pk__in=related.values("id")), many=True).data,
            "definitions": (
                "指定计划报告保留该计划当前轮次历史结果；项目报告仅计当前有效计划，人工验证独立计轮。快照保留生成时的用例版本、执行和缺陷状态，不随后续变更改写，不代表发布准入。"
            ),
        }
        report = SavedReport.objects.create(
            project=project,
            created_by=request.user,
            name=data["name"],
            plan_id=plan_id,
            request_id=data["request_id"],
            request_hash=fingerprint,
            snapshot=json.loads(JSONRenderer().render(snapshot)),
        )
        return Response(ReportSerializer(report).data, status=201)


class ReportDetail(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(ReportSerializer(self.obj(SavedReport, pk)).data)

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(RenameInput)
        report = get_object_or_404(SavedReport.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if report.edit_version != data["expected_version"]:
            raise Conflict()
        report.name = data["name"]
        report.edit_version += 1
        report.save(update_fields=["name", "edit_version"])
        return Response(ReportSerializer(report).data)


class ReportDownload(QualityView):
    def get(self, request, pk, **kwargs):
        report = self.obj(SavedReport, pk)

        def cell(value):
            return str(value or "—").replace("|", "\\|").replace("\n", " ").replace("\r", " ")

        snapshot = report.snapshot
        summary = snapshot["summary"]
        lines = [
            f"# {report.name}",
            "",
            f"项目：{snapshot['project_name']}",
            "",
            f"生成时间：{report.created_at.isoformat()}",
            "",
            snapshot["definitions"],
            "",
            "## 执行概况",
            "",
            "| 总条目 | 已执行 | 通过 | 失败 | 阻塞 | 无法判定 | 跳过 | 未执行 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
            "| "
            + " | ".join(
                str(summary.get(key, 0))
                for key in [
                    "total",
                    "executed",
                    "passed",
                    "failed",
                    "blocked",
                    "inconclusive",
                    "skipped",
                    "pending",
                ]
            )
            + " |",
            "",
            f"执行率：{summary['execution_rate']}% · 通过率：{summary['pass_rate']}%",
            "",
        ]
        conclusion = getattr(report, "conclusion", None)
        if conclusion:
            labels = {"passed": "通过", "failed": "不通过", "blocked": "阻塞", "inconclusive": "无法判定"}
            lines[8:8] = [
                "## 经理最终结论",
                "",
                f"结论：{labels[conclusion.result]}",
                "",
                conclusion.summary,
                "",
                "风险与后续事项：" + (conclusion.risks or "未单独记录"),
                "",
                f"签署时间：{conclusion.created_at.isoformat()} · 报告版本：{conclusion.report_version}",
                "",
                "此结论不代替发布准入检查。",
                "",
            ]
        results = {
            "passed": "通过",
            "failed": "失败",
            "blocked": "阻塞",
            "inconclusive": "无法判定",
            "skipped": "跳过",
        }
        manual = snapshot.get("manual_verification")
        if manual is not None:
            lines.extend(
                [
                    "## 人工验证（独立验证轮次）",
                    "",
                    f"当前轮次：{manual['total']} · 已实测：{manual['executed']} · "
                    f"通过：{manual['passed']} · 未实测：{manual['pending']}",
                    "",
                    "人工验证不计入测试用例条目或用例通过率。",
                    "",
                ]
            )
        for plan in snapshot["plans"]:
            lines.extend(
                [
                    f"## {plan['name']}",
                    "",
                    f"版本：{plan['build']} · 环境：{plan['environment']}",
                    "",
                    "| 测试用例 | 固定版本 | 最新结果 | 实际表现 | 原因 | 下一步 |",
                    "| --- | --- | --- | --- | --- | --- |",
                ]
            )
            for item in plan["items"]:
                execution = item["latest_execution"] or {}
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            cell(item["revision"]["title"]),
                            str(item["revision"]["version"]),
                            results.get(execution.get("result"), "未执行"),
                            cell(execution.get("actual_result")),
                            {"recollection": "需要补采", "environment": "环境待处理", "other": "其他"}.get(
                                execution.get("reason_category"), "—"
                            ),
                            cell(execution.get("next_action")),
                        ]
                    )
                    + " |"
                )
            lines.append("")
        lines.extend(["## 关联缺陷", "", "| 缺陷 | 状态 | 处理说明 |", "| --- | --- | --- |"])
        statuses = {"open": "待处理", "in_progress": "处理中", "pending_tech": "待技术确认", "needs_tech": "待技术处理", "resolved": "待回归", "closed": "已关闭"}
        for defect in snapshot["defects"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        cell(defect["title"]),
                        statuses.get(defect["status"], defect["status"]),
                        cell(defect["resolution"]),
                    ]
                )
                + " |"
            )
        if not snapshot["defects"]:
            lines.append("| 无关联缺陷 | — | — |")
        lines.extend(["", "## 原始快照", "", "```json", json.dumps(snapshot, ensure_ascii=False, indent=2), "```", ""])
        content = "\n".join(lines)
        response = HttpResponse(content, content_type="text/markdown; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="quality-report-{report.id}.md"'
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


def conclusion_representation(row):
    return {
        "id": str(row.id),
        "result": row.result,
        "summary": row.summary,
        "risks": row.risks,
        "report_version": row.report_version,
        "reviewed_at": row.created_at,
        "reviewer": row.created_by.display_name if row.created_by else "",
    }


class ConclusionInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    result = serializers.ChoiceField(choices=["passed", "failed", "blocked", "inconclusive"])
    summary = serializers.CharField(max_length=10000)
    risks = serializers.CharField(max_length=10000, allow_blank=True, default="")


class ReportConclude(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        from .data_regression import manager
        from rest_framework.exceptions import PermissionDenied, ValidationError

        if not manager(self.project_id, request.user):
            raise PermissionDenied("最终结论由项目经理确认。")
        data = self.input(ConclusionInput)
        report = get_object_or_404(SavedReport.objects.select_for_update(), pk=pk, project_id=self.project_id)
        existing = ReportConclusion.objects.filter(report=report).first()
        if existing:
            if (
                existing.result != data["result"]
                or existing.summary != data["summary"]
                or existing.risks != data["risks"]
                or existing.report_version != data["expected_version"]
            ):
                raise Conflict("已签署结论不可改写；补充测试后请生成新报告。")
            return Response(conclusion_representation(existing))
        if report.edit_version != data["expected_version"]:
            raise Conflict()
        if data["result"] == "passed":
            summary = report.snapshot.get("summary", {})
            manual = report.snapshot.get("manual_verification") or {}
            if (
                not (summary.get("total") or manual.get("total"))
                or summary.get("passed") != summary.get("total")
                or manual.get("passed", 0) != manual.get("total", 0)
                or manual.get("accepted", 0) != manual.get("total", 0)
                or any(summary.get(key) for key in ["pending", "failed", "blocked", "inconclusive", "skipped"])
                or any(
                    plan.get("managed") and (plan.get("status") != "completed" or not plan.get("reviewed_at"))
                    for plan in report.snapshot.get("plans", [])
                )
                or any(defect.get("status") != "closed" for defect in report.snapshot.get("defects", []))
            ):
                raise ValidationError({"result": "快照仍有未通过、未经理验收的测试或未关闭缺陷，不能签署通过结论。"})
        row = ReportConclusion.objects.create(
            project=report.project,
            report=report,
            created_by=request.user,
            report_version=data.pop("expected_version"),
            **data,
        )
        return Response(conclusion_representation(row), status=201)
