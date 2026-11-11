# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from .models import Defect, DefectCollaborator, DefectEvent
from .permissions import require_assignee
from .views import QualityView, Conflict, defect_queryset
from .serializers import DefectSerializer
from .data_regression import manager
from .notifications import notify


class TeamInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=["add", "remove", "transfer", "accept", "decline", "cancel_transfer"])
    expected_version = serializers.IntegerField(min_value=1)
    user_id = serializers.UUIDField(required=False)
    reason = serializers.CharField(max_length=4000, allow_blank=True, default="")


class DefectTeam(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(TeamInput)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data["expected_version"] != defect.edit_version:
            raise Conflict()
        action = data["action"]
        target = data.get("user_id")
        reason = data["reason"].strip()
        if action in {"accept", "decline"}:
            if defect.pending_assignee_id != request.user.id:
                raise PermissionDenied("只有指定的接收人可确认交接。")
            self.validate_assignee(request.user.id)
            require_assignee(self, request.user.id, "TECHNICIAN")
        elif not manager(self.project_id, request.user):
            raise PermissionDenied("协作者和负责人交接由项目经理管理。")
        if defect.status == "closed":
            raise Conflict("已关闭缺陷请先重开后处理协作。")
        if action in {"add", "remove", "transfer"}:
            if not target:
                raise ValidationError({"user_id": "请选择成员。"})
            self.validate_assignee(target)
        if action == "add":
            DefectCollaborator.objects.get_or_create(
                project=defect.project, defect=defect, user_id=target, defaults={"created_by": request.user}
            )
            note = "添加协作者"
        elif action == "remove":
            defect.collaborators.filter(user_id=target).delete()
            note = "移除协作者"
        elif action == "transfer":
            if not reason:
                raise ValidationError({"reason": "请填写交接原因。"})
            if defect.pending_assignee_id:
                raise Conflict("已有待确认交接，请先取消或完成。")
            if target == defect.assignee_id:
                raise ValidationError({"user_id": "请选择不同的技术负责人。"})
            require_assignee(self, target, "TECHNICIAN")
            defect.pending_assignee_id = target
            defect.transfer_reason = reason
            note = f"发起交接，等待接收人确认：{reason}"
        elif action == "accept":
            reason = defect.transfer_reason
            defect.assignee_id = request.user.id
            defect.pending_assignee = None
            note = f"接收交接：{reason}"
        elif action == "decline":
            if not reason:
                raise ValidationError({"reason": "请填写拒绝交接原因。"})
            defect.pending_assignee = None
            note = f"拒绝交接：{reason}"
        else:
            if not defect.pending_assignee_id:
                raise Conflict("当前没有待确认的交接。")
            defect.pending_assignee = None
            note = "取消待确认交接"
        defect.edit_version += 1
        defect.save()
        DefectEvent.objects.create(
            project=defect.project,
            created_by=request.user,
            defect=defect,
            previous_status=defect.status,
            status=defect.status,
            note=note,
        )
        notify(
            defect.project,
            request.user,
            [target, defect.assignee_id, defect.created_by_id],
            defect.id,
            f"{note} · {defect.title}",
            f"defects?defect={defect.id}",
        )
        return Response(DefectSerializer(defect_queryset().get(pk=defect.pk)).data)
