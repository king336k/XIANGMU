"""Defect-scoped validation reuses native case revisions, plans and executions."""

import hashlib
import json
from uuid import uuid4

from django.db import transaction
from django.db.models import F, Q, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from plane.db.models import ProjectMember
from .models import (
    Defect,
    DefectEvent,
    DefectVerification as Verification,
    DefectVerificationCase,
    DefectVerificationCaseExecution as VerificationCaseExecutionRecord,
    DefectVerificationEvent as Event,
    DefectVerificationResult as ManualResult,
    PlanItem,
    TestCase,
    TestPlan,
    BusinessNumber,
)
from .permissions import capable, strict, writable_member, is_administrator, has_role, roles_for
from .serializers import ExecutionInput, ExecutionSerializer, StepInput, RESULTS
from .views import Conflict, QualityView


class ConfigureInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    request_id = serializers.UUIDField()
    mode = serializers.ChoiceField(choices=["manual", "cases"])
    fixed_build = serializers.CharField(max_length=120)
    environment = serializers.CharField(max_length=255)
    steps = StepInput(many=True, max_length=100, required=False)
    case_ids = serializers.ListField(child=serializers.UUIDField(), max_length=500, required=False, default=list)
    test_requirements = serializers.CharField(max_length=4000, allow_blank=True, required=False, default="")
    assignee_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, data):
        field = "steps" if data["mode"] == "manual" else "case_ids"
        if data["mode"] == "manual" and not data.get("steps"):
            raise ValidationError({field: "请填写如何测试。"})
        if data["mode"] == "cases" and not data.get("case_ids") and not data["test_requirements"].strip():
            raise ValidationError({field: "请关联用例，或填写测试要求后由测试员补充本轮用例。"})
        if data["mode"] == "cases" and len(data[field]) != len(set(data[field])):
            raise ValidationError({field: "不能重复选择同一用例。"})
        return data


class ResultInput(ExecutionInput):
    expected_version = serializers.IntegerField(min_value=1)


class RoundCaseInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    request_id = serializers.UUIDField()
    case_ids = serializers.ListField(child=serializers.UUIDField(), max_length=500, required=False, default=list)
    temporary_cases = serializers.ListField(child=serializers.DictField(), max_length=100, required=False, default=list)

    def validate_temporary_cases(self, rows):
        parsed = []
        for index, row in enumerate(rows):
            serializer = TemporaryCaseInput(data=row)
            serializer.is_valid(raise_exception=True)
            parsed.append(serializer.validated_data)
        return parsed

    def validate(self, attrs):
        if not attrs.get("case_ids") and not attrs.get("temporary_cases"):
            raise ValidationError("请选择用例或补充本轮临时用例。")
        return attrs


class TemporaryCaseInput(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    preconditions = serializers.CharField(max_length=20000, allow_blank=True, default="")
    steps = StepInput(many=True, allow_empty=False, max_length=100)


class RoundCaseExecutionInput(ExecutionInput):
    expected_version = serializers.IntegerField(min_value=1)


class WorkflowInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    request_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=["assign", "submit", "accept", "return_test", "return_repair", "reopen"])
    assignee_id = serializers.UUIDField(required=False, allow_null=True)
    comment = serializers.CharField(max_length=4000, allow_blank=True, default="")


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def latest(defect):
    return defect.verification_rounds.order_by("-round_no").first()


def manager(view):
    return is_administrator(view.request.user) or (
        capable(view.project_id, view.request.user.id, "manage_test")
        if strict(view.project_id)
        else ProjectMember.objects.filter(
            project_id=view.project_id, member=view.request.user, is_active=True, role=20
        ).exists()
    )


def scheduler(view):
    return manager(view) or has_role(view.project_id, view.request.user.id, "TECHNICIAN")


def execution_state(row):
    if row.status != "testing":
        return row.status
    if row.defect.status not in {"resolved", "closed"}:
        return "waiting_repair"
    if row.fixed_build != row.defect.fixed_build or row.resolved_at not in {None, row.defect.resolved_at}:
        return "needs_arrangement"
    if row.plan_id and (row.plan.archived_at or row.plan.build != row.fixed_build or row.plan.round_no != row.round_no):
        return "needs_arrangement"
    if row.mode == "cases" and (
        row.plan.items.exclude(revision__version=F("case__version")).exists()
        or row.case_items.filter(source="library").exclude(source_case__version=F("source_revision__version")).exists()
    ):
        return "needs_arrangement"
    if row.plan_id and not row.plan.assignee_id:
        return "needs_assignment"
    if row.mode == "cases" and not row.case_items.exists() and not (row.plan_id and row.plan.items.exists()):
        return "needs_cases"
    _, summary = results(row)
    if summary["pending"] == summary["total"]:
        return "pending"
    return "tested" if not summary["pending"] else "running"


def sync_plan(row):
    if not row.plan_id:
        return
    state = execution_state(row)
    status = {
        "review": "review",
        "accepted": "completed",
        "waiting_repair": "pending",
        "needs_arrangement": "pending",
        "needs_assignment": "pending",
        "returned_repair": "cancelled",
        "reopened": "cancelled",
        "superseded": "cancelled",
    }.get(state, "running")
    if row.plan.status != status:
        row.plan.status = status
        row.plan.workflow_version += 1
        row.plan.save(update_fields=["status", "workflow_version"])


def require_executor(row, user):
    if is_administrator(user):
        return
    if not row.plan_id or not row.plan.assignee_id:
        raise PermissionDenied("请联系技术负责人或项目经理安排测试员。")
    if row.plan.assignee_id != user.id:
        raise PermissionDenied("此验证已指派给其他测试员。")


def validate_tester(view, assignee):
    if assignee is None:
        return
    member = ProjectMember.objects.filter(
        project_id=view.project_id,
        member_id=assignee,
        is_active=True,
        role__gte=15,
        member__is_active=True,
        member__member_workspace__workspace__slug=view.workspace_slug,
        member__member_workspace__is_active=True,
        member__member_workspace__role__gte=15,
    ).exists()
    if is_administrator(assignee):
        raise ValidationError({"assignee_id": "管理员可代执行，无需作为测试员指派。"})
    if not member or not capable(view.project_id, assignee, "execute"):
        raise ValidationError({"assignee_id": "请选择当前项目的测试员。"})
    roles = roles_for(view.project_id, assignee)
    if roles:
        if "REGRESSION_TESTER" not in roles:
            raise ValidationError({"assignee_id": "请选择测试员角色账号。"})
    else:
        legacy_tester = ProjectMember.objects.filter(
            project_id=view.project_id,
            member_id=assignee,
            is_active=True,
            role=15,
            member__is_active=True,
        ).exists()
        if not legacy_tester:
            raise ValidationError({"assignee_id": "请选择测试员账号。"})


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
    if row.case_items.filter(source="library").exists():
        list(
            TestCase.objects.select_for_update()
            .filter(pk__in=row.case_items.filter(source="library").values("source_case_id"))
            .order_by("id")
        )
        if row.case_items.filter(source="library").exclude(source_case__version=F("source_revision__version")).exists():
            raise Conflict("用例库已产生新版本，请新建验证轮次后重新执行。")


def results(row):
    items = []
    if row.mode == "cases":
        round_items = row.case_items.all()
        if round_items.exists():
            for item in round_items.select_related("source_case", "source_revision").prefetch_related("executions__created_by"):
                execution_history = list(item.executions.select_related("created_by").order_by("-created_at", "-id"))
                execution = execution_history[0] if execution_history else None
                items.append(
                    {
                        "item_id": str(item.id),
                        "case_id": str(item.source_case_id) if item.source_case_id else "",
                        "case_version": item.source_revision.version if item.source_revision_id else 0,
                        "revision_id": str(item.source_revision_id) if item.source_revision_id else None,
                        "source": item.source,
                        "title": item.title,
                        "snapshot": item.snapshot,
                        "stale": bool(item.source_case_id and item.source_case.version != item.source_revision.version),
                        "latest_execution": case_execution_data(execution) if execution else None,
                        "execution_history": [case_execution_data(row) for row in execution_history],
                        "result": execution.result if execution else "pending",
                    }
                )
            summary = {key: 0 for key in ["total", "pending", *RESULTS]}
            summary["total"] = len(items)
            for item in items:
                summary[item["result"]] += 1
            return items, summary
        for item in row.plan.items.select_related("revision", "case").order_by("created_at", "id"):
            execution = item.executions.filter(round_no=row.round_no).order_by("-created_at", "-id").first()
            items.append(
                {
                    "item_id": str(item.id),
                    "case_id": str(item.case_id),
                    "case_version": item.revision.version,
                    "revision_id": str(item.revision_id),
                    "source": "legacy",
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


def case_execution_data(execution):
    return {
        "id": str(execution.id),
        "result": execution.result,
        "actual_result": execution.actual_result,
        "evidence": execution.evidence,
        "step_results": execution.step_results,
        "reason_category": execution.reason_category,
        "next_action": execution.next_action,
        "created_at": execution.created_at,
        "plan_id": str(execution.item.verification.plan_id),
        "plan_name": execution.item.verification.plan.name,
        "build": execution.item.verification.fixed_build,
        "environment": execution.item.verification.environment,
        "case_id": str(execution.item.source_case_id) if execution.item.source_case_id else "",
        "case_title": execution.item.title,
        "case_version": execution.item.source_revision.version if execution.item.source_revision_id else 0,
        "executor": (execution.created_by.display_name or execution.created_by.username)
        if execution.created_by_id else "",
    }


def snapshot_legacy_plan_items(row, actor):
    """Freeze legacy public items into round scope before appending new round cases."""
    if row.case_items.exists() or not row.plan_id:
        return
    position = 0
    for plan_item in row.plan.items.select_related("case", "revision").order_by("created_at", "id"):
        item = DefectVerificationCase.objects.create(
            project=row.project,
            created_by=actor,
            verification=row,
            source_case=plan_item.case,
            source_revision=plan_item.revision,
            source_plan_item=plan_item,
            source="library",
            title=plan_item.revision.title,
            snapshot=plan_item.revision.snapshot,
            position=position,
        )
        position += 1
        for old in plan_item.executions.filter(round_no=row.round_no).order_by("created_at", "id"):
            execution = VerificationCaseExecutionRecord.objects.create(
                project=row.project,
                created_by=old.created_by,
                item=item,
                request_id=old.request_id,
                request_hash=fingerprint({
                    "result": old.result,
                    "actual_result": old.actual_result,
                    "evidence": old.evidence,
                    "step_results": old.step_results,
                    "reason_category": old.reason_category,
                    "next_action": old.next_action,
                }),
                source_execution=old,
                result=old.result,
                actual_result=old.actual_result,
                evidence=old.evidence,
                step_results=old.step_results,
                reason_category=old.reason_category,
                next_action=old.next_action,
            )
            VerificationCaseExecutionRecord.objects.filter(pk=execution.pk).update(created_at=old.created_at)


def serialize(row, view):
    items, summary = results(row)
    fresh = (
        row.defect.status == "resolved"
        and row.fixed_build == row.defect.fixed_build
        and row.resolved_at in {None, row.defect.resolved_at}
        and not any(item.get("stale") for item in items)
        and (
            not row.plan_id
            or (not row.plan.archived_at and row.plan.build == row.fixed_build and row.plan.round_no == row.round_no)
        )
    )
    administrator = is_administrator(view.request.user)
    writable = administrator or writable_member(view.project_id, view.request.user.id, view.workspace_slug)
    mutable = writable and row.status == "testing" and fresh
    is_manager = writable and manager(view)
    can_execute = writable and (
        administrator
        or (capable(view.project_id, view.request.user.id, "execute") and row.plan_id and row.plan.assignee_id == view.request.user.id)
    )
    state = execution_state(row)
    blocked = {
        "waiting_repair": "等待技术员修复",
        "needs_arrangement": "修复版本已更新，请重新安排验证",
        "needs_assignment": "请技术负责人、项目经理或管理员安排测试员",
        "needs_cases": "请补充本轮用例",
    }.get(state, "")
    return {
        "id": str(row.id),
        "defect_id": str(row.defect_id),
        "round_no": row.round_no,
        "version": row.version,
        "mode": row.mode,
        "status": row.status,
        "execution_state": state,
        "blocked_reason": blocked,
        "assignee_id": str(row.plan.assignee_id) if row.plan_id and row.plan.assignee_id else None,
        "assignee_name": (row.plan.assignee.display_name or row.plan.assignee.username)
        if row.plan_id and row.plan.assignee_id
        else "",
        "fixed_build": row.fixed_build,
        "environment": row.environment,
        "steps": row.steps,
        "test_requirements": row.steps[0]["action"] if row.mode == "cases" and row.steps else "",
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
        and scheduler(view),
        "can_accept": row.status == "review" and is_manager and fresh,
        "can_return_test": row.status == "review" and is_manager,
        "can_return_repair": row.status in {"testing", "review"} and row.defect.status == "resolved" and is_manager,
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
        steps=data.get("steps", []) if data["mode"] == "manual" else (
            [{"action": data["test_requirements"], "expected": ""}] if data.get("test_requirements") else []
        ),
        resolved_at=defect.resolved_at,
    )
    plan = TestPlan.objects.create(
        project=defect.project,
        created_by=actor,
        name=f"{defect.title} · {'人工验证' if row.mode == 'manual' else '用例回归'} · 第{number}轮"[:255],
        build=row.fixed_build,
        environment=row.environment,
        description=(row.steps[0]["action"] if row.steps else ""),
        round_no=number,
        assignee_id=data.get("assignee_id", previous.plan.assignee_id if previous and previous.plan_id else None),
        status="running" if defect.status == "resolved" else "pending",
    )
    row.plan = plan
    row.save(update_fields=["plan"])
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
        for index, case in enumerate(cases):
            revision = case.revisions.get(version=case.version)
            DefectVerificationCase.objects.create(
                project=defect.project,
                created_by=actor,
                verification=row,
                source_case=case,
                source_revision=revision,
                source="library",
                title=revision.title,
                snapshot=revision.snapshot,
                position=index,
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
        if not scheduler(self):
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
        if not data.get("assignee_id"):
            raise ValidationError({"assignee_id": "安排验证时必须指定测试员。"})
        validate_tester(self, data["assignee_id"])
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
            unchanged = True
        elif unchanged:
            current_case_ids = set(
                old.case_items.filter(source_case__isnull=False).values_list("source_case_id", flat=True)
            )
            if not old.case_items.exists() and old.plan_id:
                current_case_ids = set(old.plan.items.values_list("case_id", flat=True))
            unchanged = (
                current_case_ids == set(data["case_ids"])
                and not old.case_items.filter(source="library")
                .exclude(source_case__version=F("source_revision__version"))
                .exists()
            )
        if unchanged:
            if old.mode == "manual" and old.steps != data["steps"]:
                if old.manual_results.exists():
                    raise Conflict("本轮已有测试结果，修改测试要求请重新安排以保留历史。")
                old.steps = data["steps"]
                old.version += 1
                old.save(update_fields=["steps", "version"])
                Event.objects.create(
                    project=defect.project,
                    created_by=request.user,
                    verification=old,
                    request_id=uuid4(),
                    request_hash=hashlib.sha256(json.dumps(data["steps"], sort_keys=True).encode()).hexdigest(),
                    action="requirements_updated",
                    note="更新人工验证要求",
                    snapshot={"steps": data["steps"]},
                )
                audit(defect, request.user, "更新人工验证要求")
            if old.mode == "cases":
                previous_requirements = old.steps[0]["action"] if old.steps else ""
                next_requirements = data["test_requirements"].strip()
                if previous_requirements != next_requirements:
                    if old.case_items.filter(executions__isnull=False).exists() or (
                        old.plan_id and TestExecution.objects.filter(item__plan=old.plan).exists()
                    ):
                        raise Conflict("本轮已有执行结果，修改测试要求请重新安排验证以保留历史。")
                    old.steps = [{"action": next_requirements, "expected": ""}] if next_requirements else []
                    old.version += 1
                    old.save(update_fields=["steps", "version"])
                    if old.plan_id:
                        old.plan.description = next_requirements
                        old.plan.workflow_version += 1
                        old.plan.save(update_fields=["description", "workflow_version"])
                    Event.objects.create(
                        project=defect.project,
                        created_by=request.user,
                        verification=old,
                        request_id=uuid4(),
                        request_hash=hashlib.sha256(next_requirements.encode()).hexdigest(),
                        action="requirements_updated",
                        note="更新本轮测试要求",
                        snapshot={"test_requirements": next_requirements},
                    )
                    audit(defect, request.user, "更新本轮测试要求")
            if "assignee_id" in data and old.plan_id and old.plan.assignee_id != data["assignee_id"]:
                previous_assignee_id = old.plan.assignee_id
                old.plan.assignee_id = data["assignee_id"]
                old.plan.save(update_fields=["assignee"])
                old.version += 1
                old.save(update_fields=["version"])
                defect.edit_version += 1
                defect.save(update_fields=["edit_version", "updated_at"])
                audit(defect, request.user, "调整测试负责人")
                from .notifications import plan_notice

                plan_notice(old.plan, "assign", request.user)
                if previous_assignee_id:
                    from .notifications import notify

                    notify(
                        defect.project,
                        request.user,
                        [previous_assignee_id],
                        old.plan_id,
                        f"测试已改派：{defect.title}",
                        f"quality?tab=plans&plan={old.plan_id}",
                    )
            return Response(payload(defect, self))
        row = create_round(defect, request.user, data, old)
        from .notifications import plan_notice

        plan_notice(row.plan, "assign", request.user)
        audit(
            defect,
            request.user,
            f"{'人工验证安排' if row.mode == 'manual' else '用例回归安排：关联' + str(len(data['case_ids'])) + '条公共用例' + ('，填写测试要求' if data['test_requirements'].strip() else '，待补充本轮用例')}，"
            f"第{row.round_no}轮，修复版本{row.fixed_build}，环境{row.environment}",
        )
        return Response(payload(defect, self), status=201)


class DefectVerificationCases(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(RoundCaseInput)
        defect, row = lock(self, pk)
        if not row or row.mode != "cases" or row.status != "testing":
            raise Conflict("当前没有可补充用例的回归轮次。")
        current_check(row, defect)
        administrator = is_administrator(request.user)
        assigned_tester = (
            row.plan_id
            and row.plan.assignee_id == request.user.id
            and capable(self.project_id, request.user.id, "execute")
        )
        if not (administrator or scheduler(self) or assigned_tester):
            raise PermissionDenied("仅安排人、被指派测试员或管理员可以补充本轮用例。")
        existing = Event.objects.filter(verification=row, request_id=data["request_id"]).first()
        if existing:
            if existing.request_hash != fingerprint(data) or existing.created_by_id != request.user.id:
                raise Conflict("提交编号已用于其他操作。")
            return Response(payload(defect, self))
        if row.version != data["expected_version"]:
            raise Conflict()
        snapshot_legacy_plan_items(row, request.user)
        selected = list(
            TestCase.objects.select_for_update()
            .filter(project=defect.project, pk__in=data["case_ids"], archived_at__isnull=True, trashed_at__isnull=True)
            .order_by("id")
        )
        if len(selected) != len(set(data["case_ids"])):
            raise ValidationError({"case_ids": "请选择当前项目中未归档的用例。"})
        duplicate = set(
            row.case_items.filter(source_case_id__in=data["case_ids"]).values_list("source_case_id", flat=True)
        )
        if duplicate:
            raise ValidationError({"case_ids": "所选用例已在本轮中，请移除重复项。"})
        position = row.case_items.count()
        created = []
        for case in selected:
            revision = case.revisions.get(version=case.version)
            created.append(
                DefectVerificationCase.objects.create(
                    project=defect.project,
                    created_by=request.user,
                    verification=row,
                    source_case=case,
                    source_revision=revision,
                    source="library",
                    title=revision.title,
                    snapshot=revision.snapshot,
                    position=position,
                )
            )
            position += 1
        for temporary in data["temporary_cases"]:
            parsed = TemporaryCaseInput(data=temporary)
            parsed.is_valid(raise_exception=True)
            value = parsed.validated_data
            created.append(
                DefectVerificationCase.objects.create(
                    project=defect.project,
                    created_by=request.user,
                    verification=row,
                    source="round",
                    title=value["title"],
                    snapshot={"title": value["title"], "preconditions": value["preconditions"], "steps": value["steps"]},
                    position=position,
                )
            )
            position += 1
        if not created:
            raise ValidationError("请添加公共用例或本轮临时用例。")
        row.version += 1
        row.save(update_fields=["version"])
        sync_plan(row)
        Event.objects.create(
            project=defect.project,
            created_by=request.user,
            verification=row,
            request_id=data["request_id"],
            request_hash=fingerprint(data),
            action="cases_added",
            note=f"补充本轮用例 {len(created)} 条",
            snapshot={"items": [{"id": str(item.id), "title": item.title, "source": item.source} for item in created]},
        )
        audit(defect, request.user, f"补充回归用例第{row.round_no}轮：{len(created)}条")
        from .notifications import plan_notice

        if row.plan_id:
            plan_notice(row.plan, "update", request.user)
        return Response(payload(defect, self), status=201)


class DefectVerificationCaseExecution(QualityView):
    @transaction.atomic
    def post(self, request, item_id, **kwargs):
        if not is_administrator(request.user) and not capable(self.project_id, request.user.id, "execute"):
            raise PermissionDenied("当前角色不能提交用例结果。")
        data = self.input(RoundCaseExecutionInput)
        item = get_object_or_404(
            DefectVerificationCase.objects.select_for_update().select_related("verification__defect"),
            pk=item_id,
            project_id=self.project_id,
        )
        defect, row = lock(self, item.verification.defect_id)
        if item.verification_id != row.id or row.mode != "cases" or row.status != "testing":
            raise Conflict("当前用例不属于可执行的验证轮次。")
        require_executor(row, request.user)
        existing = item.executions.filter(request_id=data["request_id"]).first()
        if existing:
            if existing.request_hash != fingerprint(data) or existing.created_by_id != request.user.id:
                raise Conflict("同一提交编号不能改写结果。")
            return Response(payload(defect, self))
        current_check(row, defect)
        if data["expected_version"] != row.version:
            raise Conflict()
        if not data["actual_result"].strip():
            raise ValidationError({"actual_result": "请填写本条用例的测试结果说明。"})
        execution = VerificationCaseExecutionRecord.objects.create(
            project=defect.project,
            created_by=request.user,
            item=item,
            request_id=data["request_id"],
            request_hash=fingerprint(data),
            result=data["result"],
            actual_result=data["actual_result"],
            evidence=data["evidence"],
            step_results=[],
            reason_category=data["reason_category"],
            next_action=data["next_action"],
        )
        row.version += 1
        row.save(update_fields=["version"])
        sync_plan(row)
        Event.objects.create(
            project=defect.project,
            created_by=request.user,
            verification=row,
            request_id=data["request_id"],
            request_hash=fingerprint(data),
            action="case_executed",
            note=f"执行用例 {item.title}：{execution.result}",
            snapshot={"item_id": str(item.id), "execution_id": str(execution.id), "result": execution.result},
        )
        audit(defect, request.user, f"执行用例第{row.round_no}轮「{item.title}」：{execution.result}")
        if is_administrator(request.user) and row.plan_id and row.plan.assignee_id:
            from .notifications import notify

            notify(
                defect.project,
                request.user,
                [row.plan.assignee_id],
                row.plan_id,
                f"管理员已代执行一条用例：{item.title}",
                f"quality?tab=plans&plan={row.plan_id}",
            )
        return Response(payload(defect, self), status=201)


class DefectVerificationResult(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if not is_administrator(request.user) and not capable(self.project_id, request.user.id, "execute"):
            raise PermissionDenied("当前角色不能提交实测结果。")
        data = self.input(ResultInput)
        defect, row = lock(self, pk)
        if not row or row.mode != "manual":
            raise Conflict("请使用此缺陷关联用例的执行入口。")
        current_check(row, defect)
        require_executor(row, request.user)
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
        sync_plan(row)
        audit(defect, request.user, f"记录人工实测第{row.round_no}轮：{data['result']}")
        if is_administrator(request.user) and row.plan_id and row.plan.assignee_id:
            from .notifications import notify

            notify(
                defect.project,
                request.user,
                [row.plan.assignee_id],
                row.plan_id,
                f"管理员已代提交人工测试结果：{defect.title}",
                f"quality?tab=plans&plan={row.plan_id}",
            )
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
        if action == "assign":
            if not scheduler(self):
                raise PermissionDenied("当前账号不能指派测试员。")
            if not data.get("assignee_id"):
                raise ValidationError({"assignee_id": "请选择测试员。"})
            validate_tester(self, data["assignee_id"])
        if (
            action == "submit"
            and not (is_administrator(request.user) or capable(self.project_id, request.user.id, "execute"))
        ) or (action not in {"assign", "submit"} and not manager(self)):
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
            "assign": {"testing"},
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
            if action == "submit":
                require_executor(row, request.user)
            items, summary = results(row)
            if summary["pending"] or not summary["total"]:
                raise ValidationError({"result": "请先记录本轮全部验证的实际结果。"})
            if action == "accept" and summary["passed"] != summary["total"]:
                raise ValidationError({"result": "本轮全部验证通过后才可关闭缺陷。"})
        before = defect.status
        previous_assignee = row.plan.assignee if row.plan_id else None
        if action == "assign":
            if not row.plan_id:
                raise Conflict("请先安排验证。")
            row.plan.assignee_id = data["assignee_id"]
            row.plan.save(update_fields=["assignee"])
            defect.edit_version += 1
            defect.save(update_fields=["edit_version", "updated_at"])
        elif action == "submit":
            row.status = "review"
        elif action == "accept":
            row.status = "accepted"
            defect.status = "closed"
            defect.edit_version += 1
            defect.save()
        elif action == "return_test":
            if defect.status != "resolved":
                raise Conflict("请先重新修复缺陷。")
            snapshot_legacy_plan_items(row, request.user)
            row.status = "returned_test"
            row.save(update_fields=["status"])
            next_round = create_round(
                defect,
                request.user,
                {
                    "request_id": data["request_id"],
                    "mode": row.mode,
                    "fixed_build": defect.fixed_build,
                    "environment": row.environment,
                    "steps": row.steps,
                    "test_requirements": row.steps[0]["action"] if row.mode == "cases" and row.steps else "",
                    "case_ids": list(row.case_items.filter(source_case__isnull=False).values_list("source_case_id", flat=True)),
                },
                row,
            )
            if row.mode == "cases":
                for index, old_item in enumerate(row.case_items.filter(source="round").order_by("position", "created_at")):
                    DefectVerificationCase.objects.create(
                        project=defect.project,
                        created_by=request.user,
                        verification=next_round,
                        source="round",
                        title=old_item.title,
                        snapshot=old_item.snapshot,
                        position=next_round.case_items.count() + index,
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
        if action != "return_test":
            sync_plan(row)
        from .notifications import plan_notice

        notice_action = {
            "assign": "assign",
            "submit": "submit",
            "accept": "approve",
            "return_test": "return",
            "return_repair": "cancel",
            "reopen": "return",
        }[action]
        plan_notice(latest(defect).plan, notice_action, request.user)
        if action == "assign" and previous_assignee and previous_assignee.id != row.plan.assignee_id:
            from .notifications import notify

            notify(
                defect.project,
                request.user,
                [previous_assignee.id],
                row.plan_id,
                f"测试已改派：{defect.title}",
                f"quality?tab=plans&plan={row.plan_id}",
            )
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
            "assign": "指派测试员",
            "submit": "提交验证结果",
            "accept": "验收关闭",
            "return_test": "退回补测",
            "return_repair": "退回修复",
            "reopen": "重开",
        }[action]
        detail = data["comment"]
        if action == "assign":
            old_name = (previous_assignee.display_name or previous_assignee.username) if previous_assignee else "未安排"
            new_assignee = row.plan.assignee
            new_name = (new_assignee.display_name or new_assignee.username) if new_assignee else "未安排"
            detail = f"{old_name} → {new_name}"
        note = f"{label}，验证第{row.round_no}轮"
        if detail.strip():
            note += f"：{detail.strip()}"
        audit(defect, request.user, note, before)
        return Response(payload(defect, self))


class DefectVerificationResults(QualityView):
    def get(self, request, **kwargs):
        defects = Defect.objects.filter(project=self.project(), verification_rounds__isnull=False).distinct()
        if request.query_params.get("current_only") == "true":
            from .views import current_verifications

            current = current_verifications(self.project())
            mode = request.query_params.get("mode")
            if mode:
                if mode not in {"manual", "cases"}:
                    raise ValidationError({"mode": "请选择人工或用例验证。"})
                current = current.filter(mode=mode)
            if request.query_params.get("result"):
                result = serializers.ChoiceField(choices=[*RESULTS, "pending"]).run_validation(
                    request.query_params["result"]
                )
                latest_result = ManualResult.objects.filter(verification_id=OuterRef("pk")).order_by(
                    "-created_at", "-id"
                )
                current = current.filter(mode="manual").annotate(
                    latest_result=Subquery(latest_result.values("result")[:1])
                )
                current = (
                    current.filter(latest_result__isnull=True)
                    if result == "pending"
                    else current.filter(latest_result=result)
                )
            defects = defects.filter(pk__in=current.values("defect_id"))
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


def lock_execution(item_id, project_id, user=None):
    row = Verification.objects.filter(plan__items__id=item_id, project_id=project_id).first()
    if not row:
        return None
    defect = Defect.objects.select_for_update().get(pk=row.defect_id)
    row = Verification.objects.select_for_update().get(pk=row.id)
    row.plan = TestPlan.objects.select_for_update().get(pk=row.plan_id)
    current_check(row, defect)
    if user is not None:
        require_executor(row, user)
    if row.status != "testing":
        raise Conflict("本轮已提交验收，不能追加或改写执行结果。")
    return row
