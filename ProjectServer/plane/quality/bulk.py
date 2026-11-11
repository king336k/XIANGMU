# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .assets import manager
from .models import TestCase, TestPlan, TestSuite, Defect, QualityLifecycleEvent, PlanItem
from .views import QualityView, Conflict, add_revision


class ItemInput(serializers.Serializer):
    id = serializers.UUIDField()
    version = serializers.IntegerField(min_value=1)


class BulkInput(serializers.Serializer):
    resource = serializers.ChoiceField(choices=["cases", "plans", "suites", "defects"])
    action = serializers.ChoiceField(choices=["archive", "restore", "priority", "trash", "untrash"])
    items = ItemInput(many=True, allow_empty=False, max_length=100)
    priority = serializers.ChoiceField(choices=["high", "medium", "low"], required=False)
    reason = serializers.CharField(max_length=4000)


class BulkActions(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(BulkInput)
        manager(self, {"cases":"manage_case", "suites":"manage_case", "plans":"manage_test_plan"}.get(data["resource"], "manage_test"))
        model, version_field = {
            "cases": (TestCase, "version"),
            "plans": (TestPlan, "workflow_version"),
            "suites": (TestSuite, "edit_version"),
            "defects": (Defect, "edit_version"),
        }[data["resource"]]
        requested = {row["id"]: row["version"] for row in data["items"]}
        if len(requested) != len(data["items"]):
            raise ValidationError({"items": "同一条记录不能重复提交。"})
        rows = list(model.objects.select_for_update().filter(project=self.project(), pk__in=requested).order_by("id"))
        if len(rows) != len(requested):
            raise ValidationError({"items": "记录不存在或不属于当前项目。"})
        for row in rows:
            if getattr(row, version_field) != requested[row.id]:
                raise Conflict()
            if data["action"] == "priority" and (
                data["resource"] != "cases" or not data.get("priority") or row.archived_at
            ):
                raise ValidationError({"priority": "仅未归档用例可批量调整优先级。"})
            if data["action"] == "archive":
                if row.archived_at:
                    raise Conflict("所选记录已归档。")
                if data["resource"] == "plans" and row.status not in {"completed", "cancelled"}:
                    raise Conflict("仅已确认结果或已取消的计划可归档。")
                if data["resource"] == "defects" and row.status != "closed":
                    raise Conflict("缺陷须先闭环后才能归档。")
                if (
                    data["resource"] == "cases"
                    and PlanItem.objects.filter(case=row, plan__managed=True)
                    .exclude(plan__status__in=["completed", "cancelled"])
                    .exists()
                ):
                    raise Conflict("用例仍用于进行中的受管测试，暂不能归档。")
            if data["action"] == "restore" and not row.archived_at:
                raise Conflict("所选记录未归档。")
        for row in rows:
            if data["action"] in {"trash", "untrash"}:
                if data["resource"] not in {"cases", "suites"}:
                    raise ValidationError({"resource": "仅用例与用例集支持回收站。"})
                if (data["action"] == "trash") == bool(row.trashed_at):
                    raise Conflict("记录已在回收站或已恢复，请刷新后操作。")
            elif getattr(row, "trashed_at", None):
                raise Conflict("记录已在回收站，请先恢复。")
        results = []
        for row in rows:
            previous = getattr(row, version_field)
            if data["action"] == "trash":
                row.trashed_at = timezone.now()
            elif data["action"] == "untrash":
                row.trashed_at = None
            elif data["action"] == "archive":
                row.archived_at = timezone.now()
            elif data["action"] == "restore":
                row.archived_at = None
            else:
                row.priority = data["priority"]
            setattr(row, version_field, previous + 1)
            row.save()
            if data["resource"] == "cases":
                add_revision(row, request.user)
            QualityLifecycleEvent.objects.create(
                project=row.project,
                created_by=request.user,
                resource=data["resource"],
                object_id=row.id,
                action=data["action"],
                reason=data["reason"],
                before_version=previous,
                after_version=previous + 1,
            )
            results.append({"id": str(row.id), "version": previous + 1, "archived": bool(row.archived_at)})
        return Response({"items": results})
