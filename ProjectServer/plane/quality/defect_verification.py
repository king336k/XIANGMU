"""Defect-scoped validation reuses native case revisions, plans and executions."""

import hashlib
import json

from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from plane.db.models import ProjectMember
from .models import (
    Defect,
    DefectEvent,
    DefectVerification as Verification,
    DefectVerificationEvent as Event,
    DefectVerificationResult as ManualResult,
    PlanItem,
    TestCase,
    TestPlan,
    BusinessNumber,
)
from .permissions import capable, strict, writable_member
from .serializers import ExecutionInput, ExecutionSerializer, StepInput, RESULTS
from .views import Conflict, QualityView


class ConfigureInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    request_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["manual", "cases"])
    fixed_build = serializers.CharField(max_length=120)
    environment = serializers.CharField(max_length=255)
    steps = StepInput(many=True, max_length=100, required=False)
    case_ids = serializers.ListField(child=serializers.UUIDField(), max_length=500, required=False)

    def validate(self, data):
        field = "steps" if data["mode"] == "manual" else "case_ids"
        if not data.get(field):
            raise ValidationError({field: "请填写验证步骤或选择验证用例。"})
        if data["mode"] == "cases" and len(data[field]) != len(set(data[field])):
            raise ValidationError({field: "不能重复选择同一用例。"})
        return data


class ResultInput(ExecutionInput):
    expected_version = serializers.IntegerField(min_value=1)


class WorkflowInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    request_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=["submit", "accept", "return_test", "return_repair", "reopen"])
    comment = serializers.CharField(max_length=4000, allow_blank=True, default="")


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def latest(defect):
    return defect.verification_rounds.order_by("-round_no").first()


def manager(view):
    return (
        capable(view.project_id, view.request.user.id, "manage_test")
        if strict(view.project_id)
        else ProjectMember.objects.filter(
            project_id=view.project_id, member=view.request.user, is_active=True, role=20
        ).exists()
    )


def current_check(row, defect):
    if (
        row.resolved_at is None
        and defect.status == "resolved"
        and defect.resolved_at
        and row.fixed_build == defect.fixed_build
    ):
        row.resolved_at = defect.resolved_at
        row.save(update_fields=["resolved_at"])
    if (
        latest(defect).id != row.id
        or defect.archived_at
        or defect.status != "resolved"
        or row.fixed_build != defect.fixed_build
        or row.resolved_at != defect.resolved_at
    ):
        raise Conflict("修复版本或验证轮次已变更，请重新安排验证。")
    if row.plan_id:
        # Case edits and acceptance serialize on the same case locks, so a new
        # revision cannot slip between the freshness check and final closure.
        list(TestCase.objects.select_for_update().filter(planitem__plan=row.plan).order_by("id"))
        if row.plan.archived_at or row.plan.build != row.fixed_build or row.plan.round_no != row.round_no:
            raise Conflict("验证计划已变更，请重新安排验证。")
        if row.plan.items.exclude(revision__version=F("case__version")).exists():
            raise Conflict("用例库已产生新版本，请新建验证轮次后重新执行。")


def results(row):
    items = []
    if row.mode == "cases":
        for item in row.plan.items.select_related("revision", "case").order_by("created_at", "id"):
            execution = item.executions.filter(round_no=row.round_no).order_by("-created_at", "-id").first()
            items.append(
                {
                    "item_id": str(item.id),
                    "case_id": str(item.case_id),
                    "case_version": item.revision.version,
                    "revision_id": str(item.revision_id),
                    "title": item.revision.title,
                    "snapshot": item.revision.snapshot,
                    "stale": item.case.version != item.revision.version,
                    "latest_execution": ExecutionSerializer(execution).data if execution else None,
                    "result": execution.result if execution else "pending",
                }
            )
    else:
        last = row.manual_results.order_by("-created_at", "-id").first()
        items.append({"result": last.result if last else "pending"})
    summary = {key: 0 for key in ["total", "pending", *RESULTS]}
    summary["total"] = len(items)
    for item in items:
        summary[item["result"]] += 1
    return items, summary


def serialize(row, view):
    items, summary = results(row)
    fresh = (
        row.defect.status == "resolved"
        and row.fixed_build == row.defect.fixed_build
        and row.resolved_at in {None, row.defect.resolved_at}
        and not any(item.get("stale") for item in items)
    )
    writable = writable_member(view.project_id, view.request.user.id, view.workspace_slug)
    mutable = writable and row.status == "testing" and fresh
    is_manager = writable and manager(view)
    can_execute = writable and capable(view.project_id, view.request.user.id, "execute")
    return {
        "id": str(row.id),
        "defect_id": str(row.defect_id),
        "round_no": row.round_no,
        "version": row.version,
        "mode": row.mode,
        "status": row.status,
        "fixed_build": row.fixed_build,
        "environment": row.environment,
        "steps": row.steps,
        "plan_id": str(row.plan_id) if row.plan_id else None,
        "created_at": row.created_at,
        "created_by_id": str(row.created_by_id) if row.created_by_id else None,
        "items": items if row.mode == "cases" else [],
        "summary": summary,
        "manual_results": [
            {
                "id": str(r.id),
                "result": r.result,
                "actual_result": r.actual_result,
                "evidence": r.evidence,
                "step_results": r.step_results,
                "reason_category": r.reason_category,
                "next_action": r.next_action,
                "created_at": r.created_at,
                "created_by_id": str(r.created_by_id) if r.created_by_id else None,
                "created_by_name": (r.created_by.display_name or r.created_by.username) if r.created_by_id else "",
            }
            for r in row.manual_results.select_related("created_by").all()
        ],
        "events": [
            {
                "action": e.action,
                "round_no": row.round_no,
                "actor": e.created_by.display_name if e.created_by_id else "",
                "note": e.note,
                "created_at": e.created_at,
                "created_by_id": str(e.created_by_id) if e.created_by_id else None,
            }
            for e in row.workflow_events.all()
        ],
        "can_record": mutable and can_execute,
        "can_submit": mutable and can_execute,
        "can_configure": writable
        and row.defect.status in {"open", "in_progress", "resolved"}
        and row.status not in {"review", "accepted"}
        and any(
            capable(view.project_id, view.request.user.id, cap)
            for cap in ["manage_test_plan", "manage_defect", "solution"]
        ),
        "can_accept": row.status == "review" and is_manager and fresh,
        "can_return_test": row.status == "review" and is_manager,
        "can_return_repair": row.status in {"testing", "review"} and is_manager,
        "can_reopen": row.status == "accepted" and row.defect.status == "closed" and is_manager,
    }


def payload(defect, view):
    rows = list(defect.verification_rounds.select_related("plan", "defect").order_by("-round_no"))
    return {
        "defect_id": str(defect.id),
        "defect_status": defect.status,
        "defect_version": defect.edit_version,
        "current": serialize(rows[0], view) if rows else None,
        "history": [serialize(row, view) for row in rows[1:]],
    }


def lock(view, pk):
    defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=view.project_id)
    row = Verification.objects.select_for_update().filter(defect=defect).order_by("-round_no").first()
    if row and row.plan_id:
        row.plan = TestPlan.objects.select_for_update().get(pk=row.plan_id)
    return defect, row


def create_round(defect, actor, data, previous=None):
    number = (latest(defect).round_no + 1) if latest(defect) else 1
    row = Verification.objects.create(
        project=defect.project,
        created_by=actor,
        defect=defect,
        round_no=number,
        version=previous.version + 1 if previous else 1,
        request_id=data["request_id"],
        request_hash=fingerprint(data),
        mode=data["mode"],
        fixed_build=data["fixed_build"],
        environment=data["environment"],
        steps=data.get("steps", []),
        resolved_at=defect.resolved_at,
    )
    if row.mode == "cases":
        cases = list(
            TestCase.objects.select_for_update()
            .filter(
                project=defect.project,
                pk__in=data["case_ids"],
                archived_at__isnull=True,
                trashed_at__isnull=True,
            )
            .order_by("id")
        )
        if len(cases) != len(data["case_ids"]):
            raise ValidationError({"case_ids": "请选择当前项目未归档的有效用例。"})
        plan = TestPlan.objects.create(
            project=defect.project,
            created_by=actor,
            name=f"{defect.title} · 验证第{number}轮"[:255],
            build=row.fixed_build,
            environment=row.environment,
            round_no=number,
            status="running",
        )
        for case in cases:
            PlanItem.objects.create(
                project=defect.project,
                created_by=actor,
                plan=plan,
                case=case,
                revision=case.revisions.get(version=case.version),
            )
        row.plan = plan
        row.save(update_fields=["plan"])
    if previous:
        previous.status = "superseded" if previous.status == "testing" else previous.status
        previous.version += 1
        previous.save()
        if previous.plan_id:
            previous.plan.status = "cancelled"
            previous.plan.save(update_fields=["status"])
    defect.edit_version += 1
    defect.save(update_fields=["edit_version", "updated_at"])
    return row


def audit(defect, actor, text, previous=None):
    DefectEvent.objects.create(
        project=defect.project,
        created_by=actor,
        defect=defect,
        previous_status=previous or defect.status,
        status=defect.status,
        note=text,
    )


class DefectVerification(QualityView):
    def get(self, request, pk, **kwargs):
        return Response(payload(self.obj(Defect, pk), self))

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if not any(
            capable(self.project_id, request.user.id, c) for c in ["manage_test_plan", "manage_defect", "solution"]
        ):
            raise PermissionDenied("当前角色不能配置验证。")
        data = self.input(ConfigureInput)
        defect, old = lock(self, pk)
        existing = Verification.objects.filter(defect=defect, request_id=data["request_id"]).first()
        if existing:
            if (
                existing.request_hash != fingerprint(data)
                or old.id != existing.id
                or existing.created_by_id != request.user.id
            ):
                raise Conflict("提交编号已用于其他验证配置。")
            return Response(payload(defect, self))
        if defect.edit_version != data["expected_version"]:
            raise Conflict()
        if defect.archived_at or defect.status == "closed":
            raise Conflict("请先恢复或重开缺陷，再安排验证。")
        if defect.status == "resolved" and data["fixed_build"] != defect.fixed_build:
            raise Conflict("验证版本必须与本次修复版本一致。")
        if old and old.status in {"review", "accepted"}:
            raise Conflict("请先退回测试、退回修复或重开缺陷。")
        unchanged = (
            old
            and old.status == "testing"
            and old.mode == data["mode"]
            and old.fixed_build == data["fixed_build"]
            and old.resolved_at == defect.resolved_at
            and old.environment == data["environment"]
        )
        if unchanged and old.mode == "manual":
            unchanged = old.steps == data["steps"]
        elif unchanged:
            unchanged = (
                set(old.plan.items.values_list("case_id", flat=True)) == set(data["case_ids"])
                and not old.plan.items.exclude(revision__version=F("case__version")).exists()
            )
        if unchanged:
            return Response(payload(defect, self))
        row = create_round(defect, request.user, data, old)
        audit(
            defect,
            request.user,
            f"{'人工验证安排' if row.mode == 'manual' else '关联' + str(len(data['case_ids'])) + '条用例'}，"
            f"第{row.round_no}轮，修复版本{row.fixed_build}，环境{row.environment}",
        )
        return Response(payload(defect, self), status=201)


class DefectVerificationResult(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if not capable(self.project_id, request.user.id, "execute"):
            raise PermissionDenied("当前角色不能提交实测结果。")
        data = self.input(ResultInput)
        defect, row = lock(self, pk)
        if not row or row.mode != "manual":
            raise Conflict("请使用此缺陷关联用例的执行入口。")
        current_check(row, defect)
        existing = ManualResult.objects.filter(verification__defect=defect, request_id=data["request_id"]).first()
        if existing:
            if (
                existing.verification_id != row.id
                or existing.request_hash != fingerprint(data)
                or existing.created_by_id != request.user.id
            ):
                raise Conflict("同一提交编号不能改写结果。")
            return Response(payload(defect, self))
        if data["expected_version"] != row.version or row.status != "testing":
            raise Conflict()
        validate_actual(data, row.steps)
        ManualResult.objects.create(
            project=defect.project,
            created_by=request.user,
            verification=row,
            request_id=data["request_id"],
            request_hash=fingerprint(data),
            **{
                key: data[key]
                for key in [
                    "result",
                    "actual_result",
                    "evidence",
                    "step_results",
                    "reason_category",
                    "next_action",
                ]
            },
        )
        row.version += 1
        row.save(update_fields=["version"])
        audit(defect, request.user, f"记录人工实测第{row.round_no}轮：{data['result']}")
        return Response(payload(defect, self), status=201)


def validate_actual(data, steps):
    if len(data["step_results"]) != len(steps) or any(not step["actual"].strip() for step in data["step_results"]):
        raise ValidationError({"step_results": "请逐步填写实际结果。"})
    if data["result"] == "passed" and any(s["result"] != "passed" for s in data["step_results"]):
        raise ValidationError({"result": "存在未通过步骤，不能标记通过。"})


class DefectVerificationWorkflow(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(WorkflowInput)
        action = data["action"]
        if (action == "submit" and not capable(self.project_id, request.user.id, "execute")) or (
            action != "submit" and not manager(self)
        ):
            raise PermissionDenied("仅项目经理或管理员可以最终验收、退回或重开。")
        defect, row = lock(self, pk)
        if not row or defect.archived_at:
            raise Conflict("当前缺陷没有可操作的验证轮次。")
        existing = Event.objects.filter(verification__defect=defect, request_id=data["request_id"]).first()
        if existing:
            if existing.request_hash != fingerprint(data) or existing.created_by_id != request.user.id:
                raise Conflict("同一提交编号不能用于其他操作。")
            return Response(payload(defect, self))
        if row.version != data["expected_version"]:
            raise Conflict()
        allowed = {
            "submit": {"testing"},
            "accept": {"review"},
            "return_test": {"review"},
            "return_repair": {"testing", "review"},
            "reopen": {"accepted"},
        }
        if row.status not in allowed[action]:
            raise Conflict("当前验证状态不允许此操作。")
        if action in {"return_test", "return_repair", "reopen"} and not data["comment"].strip():
            raise ValidationError({"comment": "请说明退回或重开原因。"})
        if action in {"submit", "accept"}:
            current_check(row, defect)
            items, summary = results(row)
            if summary["pending"] or not summary["total"]:
                raise ValidationError({"result": "请先记录本轮全部验证的实际结果。"})
            if action == "accept" and summary["passed"] != summary["total"]:
                raise ValidationError({"result": "本轮全部验证通过后才可关闭缺陷。"})
        before = defect.status
        if action == "submit":
            row.status = "review"
        elif action == "accept":
            row.status = "accepted"
            defect.status = "closed"
            defect.edit_version += 1
            defect.save()
        elif action == "return_test":
            if defect.status != "resolved":
                raise Conflict("请先重新修复缺陷。")
            row.status = "returned_test"
            row.save(update_fields=["status"])
            create_round(
                defect,
                request.user,
                {
                    "request_id": data["request_id"],
                    "mode": row.mode,
                    "fixed_build": defect.fixed_build,
                    "environment": row.environment,
                    "steps": row.steps,
                    "case_ids": list(row.plan.items.values_list("case_id", flat=True)) if row.plan_id else [],
                },
                row,
            )
        else:
            if action == "reopen" and defect.status != "closed":
                raise Conflict("当前缺陷尚未关闭。")
            row.status = "reopened" if action == "reopen" else "returned_repair"
            defect.status, defect.resolved_at, defect.regression_execution = "open", None, None
            defect.edit_version += 1
            defect.save()
        if action != "return_test":
            row.version += 1
            row.save()
        if row.plan_id:
            row.plan.status = {"submit": "review", "accept": "completed"}.get(action, "cancelled")
            row.plan.save(update_fields=["status"])
        Event.objects.create(
            project=defect.project,
            created_by=request.user,
            verification=row,
            request_id=data["request_id"],
            request_hash=fingerprint(data),
            action=action,
            note=data["comment"],
            snapshot={
                "summary": results(row)[1],
                "fixed_build": row.fixed_build,
                "round_no": row.round_no,
                "execution_ids": [
                    item["latest_execution"]["id"] for item in results(row)[0] if item.get("latest_execution")
                ],
                "manual_result_id": (str(row.manual_results.first().id) if row.manual_results.exists() else None),
            },
        )
        label = {
            "submit": "提交验证结果",
            "accept": "验收关闭",
            "return_test": "退回补测",
            "return_repair": "退回修复",
            "reopen": "重开",
        }[action]
        audit(defect, request.user, f"{label}，验证第{row.round_no}轮：{data['comment']}", before)
        return Response(payload(defect, self))


class DefectVerificationResults(QualityView):
    def get(self, request, **kwargs):
        defects = Defect.objects.filter(project=self.project(), verification_rounds__isnull=False).distinct()
        search = request.query_params.get("search", "").strip()
        if search:
            identifiers = BusinessNumber.objects.filter(
                project_id=self.project_id, resource="quality.defect", code__icontains=search
            ).values_list("object_id", flat=True)
            defects = defects.filter(Q(title__icontains=search) | Q(pk__in=identifiers))
        from .views import QualityPagination
        from .numbering import preload

        paginator = QualityPagination()
        rows = paginator.paginate_queryset(defects, request)
        preload(rows)
        return paginator.get_paginated_response(
            [
                {**payload(row, self), "title": row.title, "code": row.code, "fixed_build": row.fixed_build}
                for row in rows
            ]
        )


def guard_legacy(defect, data):
    if defect.verification_rounds.exists() and (
        data.get("status") == "closed" or defect.status == "closed" and data.get("status", "closed") != "closed"
    ):
        raise Conflict("此缺陷已配置验证流程，请从验证面板验收或填写原因后重开。")


def lock_execution(item_id, project_id):
    row = Verification.objects.filter(plan__items__id=item_id, project_id=project_id).first()
    if not row:
        return None
    defect = Defect.objects.select_for_update().get(pk=row.defect_id)
    row = Verification.objects.select_for_update().get(pk=row.id)
    row.plan = TestPlan.objects.select_for_update().get(pk=row.plan_id)
    current_check(row, defect)
    if row.status != "testing":
        raise Conflict("本轮已提交验收，不能追加或改写执行结果。")
    return row
