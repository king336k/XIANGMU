# SPDX-License-Identifier: AGPL-3.0-only
from plane.quality.authorship import AuthoredRecordSerializer
from rest_framework import serializers

from .models import CaseRevision, Defect, DefectEvent, PlanEvent, PlanItem, TestCase, TestExecution, TestPlan

RESULTS = ("passed", "failed", "blocked", "inconclusive", "skipped")


class StepInput(serializers.Serializer):
    action = serializers.CharField(max_length=4000)
    expected = serializers.CharField(max_length=4000)


class CaseInput(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    module = serializers.CharField(max_length=120, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=("high", "medium", "low"), default="medium")
    preconditions = serializers.CharField(max_length=20000, allow_blank=True, default="")
    steps = StepInput(many=True, allow_empty=False, max_length=100)
    requirement_id = serializers.UUIDField(required=False, allow_null=True)
    expected_version = serializers.IntegerField(min_value=1, required=False)


class PlanInput(serializers.Serializer):
    managed = serializers.BooleanField(default=False)
    name = serializers.CharField(max_length=255)
    build = serializers.CharField(max_length=120)
    environment = serializers.CharField(max_length=255)
    description = serializers.CharField(max_length=20000, allow_blank=True, default="")
    assignee_id = serializers.UUIDField(required=False, allow_null=True)
    case_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=500, required=False)
    suite_id = serializers.UUIDField(required=False)


class StepResultInput(serializers.Serializer):
    result = serializers.ChoiceField(choices=RESULTS)
    actual = serializers.CharField(max_length=4000, allow_blank=True)


class ExecutionInput(serializers.Serializer):
    request_id = serializers.UUIDField()
    result = serializers.ChoiceField(choices=RESULTS)
    actual_result = serializers.CharField(max_length=20000, allow_blank=True, default="")
    evidence = serializers.CharField(max_length=20000, allow_blank=True, default="")
    step_results = StepResultInput(many=True, max_length=100, default=list)
    reason_category = serializers.ChoiceField(choices=["", "recollection", "environment", "other"], default="")
    next_action = serializers.CharField(max_length=4000, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs["actual_result"].strip() and attrs["step_results"]:
            attrs["actual_result"] = "\n".join(
                f"{index + 1}. {step['actual']}"
                for index, step in enumerate(attrs["step_results"])
                if step["actual"].strip()
            )[:20000]
        if attrs["result"] == "inconclusive" or any(step["result"] == "inconclusive" for step in attrs["step_results"]):
            errors = {}
            if not attrs["reason_category"]:
                errors["reason_category"] = "请选择无法判定的原因：补采、环境或其他。"
            if not attrs["actual_result"].strip():
                errors["actual_result"] = "请说明为什么无法判定。"
            if not attrs["next_action"].strip():
                errors["next_action"] = "请填写补采、环境处理或其他下一步。"
            if errors:
                raise serializers.ValidationError(errors)
        return attrs


class DefectInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1, required=False)
    case_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=255, required=False)
    severity = serializers.ChoiceField(choices=("critical", "major", "minor", "trivial"), required=False)
    description = serializers.CharField(max_length=20000, allow_blank=True, required=False)
    affected_build = serializers.CharField(max_length=120, allow_blank=True, required=False)
    fixed_build = serializers.CharField(max_length=120, allow_blank=True, required=False)
    resolution = serializers.CharField(max_length=20000, allow_blank=True, required=False)
    assignee_id = serializers.UUIDField(required=False, allow_null=True)
    repair_issue_id = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=("open", "in_progress", "resolved", "closed"), required=False)
    regression_execution_id = serializers.UUIDField(required=False)
    verification_method = serializers.ChoiceField(choices=("regression", "manual"), required=False)
    verification_note = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    verification_scope = serializers.ChoiceField(choices=("auto", "functional", "data"), required=False)
    verification_scope_reason = serializers.CharField(max_length=1000, allow_blank=True, required=False)


class CaseSerializer(AuthoredRecordSerializer):
    requirement_title = serializers.CharField(source="requirement.name", read_only=True, default=None)

    class Meta:
        model = TestCase
        fields = [
            "id",
            "title",
            "module",
            "archived_at",
            "trashed_at",
            "priority",
            "preconditions",
            "steps",
            "version",
            "requirement_id",
            "requirement_title",
            "created_at",
            "updated_at",
        ]


class RevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaseRevision
        fields = ["id", "version", "title", "snapshot", "created_at"]


class ExecutionSerializer(AuthoredRecordSerializer):
    plan_id = serializers.UUIDField(source="item.plan_id", read_only=True)
    executor = serializers.CharField(source="created_by.display_name", default="")
    case_title = serializers.CharField(source="item.revision.title", read_only=True)
    case_id = serializers.UUIDField(source="item.case_id", read_only=True)
    case_version = serializers.IntegerField(source="item.revision.version", read_only=True)
    plan_name = serializers.CharField(source="item.plan.name", read_only=True)
    build = serializers.CharField(source="item.plan.build", read_only=True)
    environment = serializers.CharField(source="item.plan.environment", read_only=True)

    class Meta:
        model = TestExecution
        fields = [
            "id",
            "item_id",
            "plan_id",
            "request_id",
            "result",
            "actual_result",
            "evidence",
            "step_results",
            "reason_category",
            "next_action",
            "created_at",
            "executor",
            "case_title",
            "case_id",
            "case_version",
            "plan_name",
            "build",
            "environment",
            "round_no",
            "resource_snapshot",
        ]


class ItemSerializer(serializers.ModelSerializer):
    current_case_version = serializers.IntegerField(source="case.version", read_only=True)
    case_archived = serializers.SerializerMethodField()

    def get_case_archived(self, obj):
        return obj.case.archived_at is not None

    revision = RevisionSerializer(read_only=True)
    latest_execution = serializers.SerializerMethodField()

    def get_latest_execution(self, obj):
        execution = next(iter(obj.latest_results), None)
        return ExecutionSerializer(execution).data if execution else None

    class Meta:
        model = PlanItem
        fields = ["id", "case_id", "revision", "latest_execution", "current_case_version", "case_archived"]


def plan_summary(plan):
    counts = {key: 0 for key in [*RESULTS, "pending"]}
    for item in plan.items.all():
        execution = next(iter(item.latest_results), None)
        counts[execution.result if execution else "pending"] += 1
    total = sum(counts.values())
    executed = total - counts["pending"]
    return {
        **counts,
        "total": total,
        "executed": executed,
        "execution_rate": round(executed * 100 / total, 1) if total else 0,
        "pass_rate": round(counts["passed"] * 100 / executed, 1) if executed else 0,
    }


class PlanEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="created_by.display_name", default="成员")

    class Meta:
        model = PlanEvent
        fields = [
            "id",
            "action",
            "previous_status",
            "status",
            "round_no",
            "note",
            "actor",
            "created_at",
            "execution_ids",
        ]


class PlanSerializer(AuthoredRecordSerializer):
    data_regression = serializers.SerializerMethodField()

    def get_data_regression(self, obj):
        row = getattr(obj, "data_regression", None)
        return (
            {
                "id": str(row.id),
                "defect_id": str(row.defect_id),
                "round_started_at": row.round_started_at,
                "task_id": row.binding.platform_task_id,
                "request_snapshot": row.request_snapshot,
            }
            if row
            else None
        )

    items = ItemSerializer(many=True, read_only=True)
    summary = serializers.SerializerMethodField()
    assignee_name = serializers.CharField(source="assignee.display_name", default="")
    workflow_events = PlanEventSerializer(many=True, read_only=True)

    def get_summary(self, obj):
        return plan_summary(obj)

    class Meta:
        model = TestPlan
        fields = [
            "id",
            "name",
            "build",
            "environment",
            "description",
            "assignee_id",
            "assignee_name",
            "created_at",
            "items",
            "summary",
            "managed",
            "archived_at",
            "data_regression",
            "status",
            "round_no",
            "workflow_version",
            "reviewed_by_id",
            "reviewed_at",
            "workflow_events",
        ]


class EventSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        import json

        try:
            note = json.loads(data["note"])
            if (
                isinstance(note, dict)
                and isinstance(note.get("message"), str)
                and ("incidentSignature" in note or "incidentSessionSignature" in note)
            ):
                data["note"] = note["message"]
        except (ValueError, TypeError):
            pass
        return data

    actor = serializers.CharField(source="created_by.display_name", default="")

    class Meta:
        model = DefectEvent
        fields = ["id", "previous_status", "status", "note", "created_at", "actor"]


class DefectSerializer(AuthoredRecordSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        from .daq_incidents import trusted_incident, signed_record

        link = trusted_incident(instance)
        if link:
            reporter = signed_record(link).get("reporter", {})
            if reporter:
                data["reporter"] = reporter
                data["created_by_name"] = reporter["username"]
        from .defect_content import defect_content

        data["title"], data["description"] = defect_content(data["title"], data["description"])
        data["has_verification"] = instance.verification_rounds.exists()
        data["source_kind"] = (
            "daq"
            if hasattr(instance, "daq_report")
            or any(
                source.source_system in {"daq", "ENGRAM_DAQ"} and source.record_type == "daq_incident"
                for source in instance.sources.all()
            )
            else "test"
            if instance.source_execution_id
            else "manual"
        )
        return data

    collaborators = serializers.SerializerMethodField()
    pending_assignee_id = serializers.UUIDField(read_only=True, allow_null=True)
    duplicate_of_id = serializers.UUIDField(read_only=True, allow_null=True)

    def get_collaborators(self, obj):
        return [
            {"user_id": str(row.user_id), "name": row.user.display_name or "成员"}
            for row in obj.collaborators.select_related("user")
        ]

    manual_verification_allowed = serializers.SerializerMethodField()
    requires_data_regression = serializers.SerializerMethodField()

    def get_requires_data_regression(self, obj):
        from .verification_scope import requires_data_regression

        return requires_data_regression(obj)

    def get_manual_verification_allowed(self, obj):
        return (
            obj.case_id is None
            and obj.source_execution_id is None
            and not self.get_requires_data_regression(obj)
            and (not obj.sources.exists() or obj.verification_scope == "functional" or self.to_daq_incident(obj))
        )

    def to_daq_incident(self, obj):
        from .daq_incidents import trusted_incident

        return trusted_incident(obj) is not None

    case_id = serializers.UUIDField(read_only=True, allow_null=True)
    case_title = serializers.CharField(source="case.title", default=None)
    repair_issue_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_execution = ExecutionSerializer(read_only=True)
    regression_execution = ExecutionSerializer(read_only=True)
    repair_issue_name = serializers.CharField(source="repair_issue.name", default=None)
    repair_issue_sequence = serializers.IntegerField(source="repair_issue.sequence_id", default=None)
    events = EventSerializer(many=True, read_only=True)
    assignee_name = serializers.CharField(source="assignee.display_name", default="")

    class Meta:
        model = Defect
        fields = [
            "id",
            "case_id",
            "case_title",
            "title",
            "severity",
            "manual_verification_allowed",
            "verification_scope",
            "requires_data_regression",
            "resolution_kind",
            "duplicate_of_id",
            "defer_until",
            "archived_at",
            "edit_version",
            "pending_assignee_id",
            "transfer_reason",
            "collaborators",
            "description",
            "affected_build",
            "fixed_build",
            "status",
            "resolution",
            "assignee_id",
            "assignee_name",
            "repair_issue_id",
            "repair_issue_name",
            "repair_issue_sequence",
            "source_execution",
            "regression_execution",
            "resolved_at",
            "created_at",
            "updated_at",
            "events",
        ]
