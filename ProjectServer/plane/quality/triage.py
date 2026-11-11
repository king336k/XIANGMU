# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import Defect, DefectEvent
from .views import QualityView, Conflict, defect_queryset
from .assets import manager
from .serializers import DefectSerializer
from .notifications import defect_notice


class DispositionInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["duplicate", "deferred", "not_reproducible", "not_a_bug", "wont_fix"])
    reason = serializers.CharField(max_length=4000)
    expected_version = serializers.IntegerField(min_value=1)
    duplicate_of_id = serializers.UUIDField(required=False)
    defer_until = serializers.DateField(required=False)


class DefectDisposition(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        manager(self)
        data = self.input(DispositionInput)
        row = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if row.edit_version != data["expected_version"]:
            raise Conflict()
        if row.archived_at or row.status == "closed":
            raise Conflict("请先恢复或重开，再调整处理分类。")
        if row.pending_assignee_id:
            raise Conflict("请先完成或取消交接。")
        if data["kind"] == "duplicate":
            if not data.get("duplicate_of_id"):
                raise ValidationError({"duplicate_of_id": "请选择主缺陷。"})
            target = get_object_or_404(
                Defect, pk=data.get("duplicate_of_id"), project_id=self.project_id, archived_at__isnull=True
            )
            if target.id == row.id or target.duplicate_of_id:
                raise ValidationError({"duplicate_of_id": "请选择当前项目的另一条主缺陷，不能指向自己或另一条重复项。"})
            row.duplicate_of = target
        if data["kind"] == "deferred":
            until = data.get("defer_until")
            if not until or until <= timezone.localdate():
                raise ValidationError({"defer_until": "延期须选择未来日期，缺陷仍保留为未关闭。"})
            row.defer_until = until
        previous = row.status
        row.resolution_kind = data["kind"]
        row.resolution = data["reason"]
        row.status = previous if data["kind"] == "deferred" else "closed"
        row.edit_version += 1
        row.save()
        names = {
            "duplicate": "重复缺陷归并",
            "deferred": "延期处理",
            "not_reproducible": "无法复现",
            "not_a_bug": "非缺陷",
            "wont_fix": "决定不修复",
        }
        note = f"项目经理确认{names[data['kind']]}：{data['reason']}。此决定不表示修复或新数据回归通过。"
        DefectEvent.objects.create(
            project=row.project,
            created_by=request.user,
            defect=row,
            previous_status=previous,
            status=row.status,
            note=note,
        )
        defect_notice(row, request.user, names[data["kind"]])
        return Response(DefectSerializer(defect_queryset().get(pk=row.id)).data)
