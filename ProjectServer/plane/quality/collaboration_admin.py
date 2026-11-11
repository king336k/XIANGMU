# SPDX-License-Identifier: AGPL-3.0-only
"""Optional routing and explicit reminders never grant access to project records."""

from datetime import timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError, Throttled
from rest_framework.response import Response
from plane.db.models import ProjectMember
from .models import (
    CollaborationSettings,
    Defect,
    DefectEvent,
    DefectReminder,
    PlatformAccount,
    PlatformIdentity,
)
from .permissions import capable, roles_for, writable_member
from .data_regression import manager
from .views import QualityView, Conflict


def internal_access(project_id, user, workspace_slug):
    if not user.is_active or not writable_member(project_id, user.id, workspace_slug):
        return False
    roles = roles_for(project_id, user.id)
    internal_roles = {"PLATFORM_ADMIN", "PROJECT_MANAGER", "TECHNICIAN", "REGRESSION_TESTER"}
    if roles and not roles & internal_roles:
        return False
    if not roles & internal_roles and (
        PlatformAccount.objects.filter(user=user, source_role="Collector").exists()
        or PlatformIdentity.objects.filter(project_id=project_id, user=user).exists()
    ):
        return False
    return capable(project_id, user.id, "comment")


def can_remind(defect, user):
    return internal_access(defect.project_id, user, defect.project.workspace.slug) and (
        manager(defect.project_id, user)
        or defect.assignee_id == user.id
        or defect.collaborators.filter(user=user).exists()
    )


class SettingsInput(serializers.Serializer):
    enabled = serializers.BooleanField()
    expected_version = serializers.IntegerField(min_value=1)
    departments = serializers.ListField(child=serializers.CharField(max_length=128), max_length=100)
    components = serializers.ListField(child=serializers.CharField(max_length=128), max_length=100)

    def validate(self, data):
        for field in ["departments", "components"]:
            if len(data[field]) != len(set(data[field])):
                raise ValidationError({field: "选项不能重复。"})
        return data


def config_data(row):
    return {
        "enabled": row.enabled if row else False,
        "departments": row.departments if row else [],
        "components": row.components if row else [],
        "version": row.version if row else 1,
    }


class ProjectCollaborationSettings(QualityView):
    def get(self, request, **kwargs):
        return Response(config_data(CollaborationSettings.objects.filter(project=self.project()).first()))

    def post(self, request, **kwargs):
        return self.put(request, **kwargs)

    @transaction.atomic
    def put(self, request, **kwargs):
        if not manager(self.project_id, request.user):
            raise PermissionDenied("只有项目经理可以配置可选路由。")
        data = self.input(SettingsInput)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        row, _ = CollaborationSettings.objects.select_for_update().get_or_create(project=project)
        if row.version != data.pop("expected_version"):
            raise Conflict()
        for key, value in data.items():
            setattr(row, key, value)
        row.version += 1
        row.created_by = request.user
        row.save()
        return Response(config_data(row))


class RoutingInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    department = serializers.CharField(max_length=128, allow_blank=True, required=False)
    component = serializers.CharField(max_length=128, allow_blank=True, required=False)


class DefectRouting(QualityView):
    def get(self, request, pk, **kwargs):
        defect = self.obj(Defect, pk)
        config = CollaborationSettings.objects.filter(project_id=self.project_id).first()
        return Response(
            {
                **config_data(config),
                "department": defect.responsible_department,
                "component": defect.component,
                "edit_version": defect.edit_version,
                "can_edit": bool(
                    not defect.archived_at
                    and defect.status != "closed"
                    and writable_member(self.project_id, request.user.id, self.workspace_slug)
                    and capable(self.project_id, request.user.id, "manage_defect")
                    and (manager(self.project_id, request.user) or defect.assignee_id == request.user.id)
                ),
            }
        )

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(RoutingInput)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if not manager(self.project_id, request.user) and defect.assignee_id != request.user.id:
            raise PermissionDenied("只有当前负责人或项目经理可以调整路由。")
        if defect.archived_at or defect.status == "closed":
            raise Conflict("缺陷已结束或归档，请先恢复。")
        if defect.edit_version != data.pop("expected_version"):
            raise Conflict()
        config = CollaborationSettings.objects.select_for_update().filter(project_id=self.project_id).first()
        for field, model_field, choices in [
            ("department", "responsible_department", "departments"),
            ("component", "component", "components"),
        ]:
            if field not in data:
                continue
            value = data[field]
            if (
                value
                and value != getattr(defect, model_field)
                and (not config or not config.enabled or value not in getattr(config, choices))
            ):
                raise ValidationError({field: "请选择本项目启用的路由选项，或留空。"})
            setattr(defect, model_field, value)
        defect.edit_version += 1
        defect.save()
        DefectEvent.objects.create(
            project=defect.project,
            defect=defect,
            created_by=request.user,
            previous_status=defect.status,
            status=defect.status,
            note=f"调整责任路由：{defect.responsible_department or '未指定部门'} / {defect.component or '未指定组件'}",
        )
        return self.get(request, pk, **kwargs)


class ReminderInput(serializers.Serializer):
    target = serializers.ChoiceField(choices=["assignee", "pending_assignee", "collaborators", "managers"])


class DefectReminders(QualityView):
    def get(self, request, pk, **kwargs):
        defect = self.obj(Defect, pk)
        return Response(
            {
                "can_remind": bool(
                    can_remind(defect, request.user) and not defect.archived_at and defect.status != "closed"
                ),
                "can_internal_comment": internal_access(self.project_id, request.user, self.workspace_slug),
                "can_public_comment": writable_member(self.project_id, request.user.id, self.workspace_slug)
                and capable(self.project_id, request.user.id, "report"),
                "cooldown_seconds": 600,
            }
        )

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if set(request.data) - {"target"}:
            raise ValidationError({"target": "请选择固定职责，不能指定任意收件人或正文。"})
        data = self.input(ReminderInput)
        defect = get_object_or_404(Defect.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if not can_remind(defect, request.user):
            raise PermissionDenied("只有当前负责人、协作者或项目经理可以催办。")
        if defect.archived_at or defect.status == "closed":
            raise Conflict("已关闭或归档缺陷不能催办。")
        target = data["target"]
        if target == "managers":
            ids = [
                m.member_id
                for m in ProjectMember.objects.filter(
                    project_id=self.project_id, is_active=True, role__gte=15
                ).select_related("member")
                if manager(self.project_id, m.member)
            ]
        elif target == "collaborators":
            ids = list(defect.collaborators.values_list("user_id", flat=True))
        else:
            ids = [getattr(defect, target + "_id")]
        members = (
            ProjectMember.objects.filter(
                project_id=self.project_id,
                member_id__in=[pk for pk in ids if pk],
                is_active=True,
                role__gte=15,
            )
            .exclude(member=request.user)
            .select_related("member")
        )
        receivers = [m.member_id for m in members if internal_access(self.project_id, m.member, self.workspace_slug)]
        if not receivers:
            raise ValidationError({"target": "当前没有其他有效的内部接收人。"})
        now = timezone.now()
        prior = {
            r.receiver_id: r
            for r in DefectReminder.objects.select_for_update().filter(defect=defect, receiver_id__in=receivers)
        }
        eligible = [pk for pk in receivers if pk not in prior or prior[pk].sent_at <= now - timedelta(minutes=10)]
        if not eligible:
            seconds = min(
                max(
                    1,
                    int((prior[pk].sent_at + timedelta(minutes=10) - now).total_seconds()) + 1,
                )
                for pk in receivers
            )
            raise Throttled(wait=seconds, detail="此缺陷已催办，请10分钟后再试。")
        from .notifications import notify

        notify(
            defect.project,
            request.user,
            eligible,
            defect.id,
            f"请跟进缺陷：{defect.title}",
            f"defects?defect={defect.id}",
        )
        for pk in eligible:
            DefectReminder.objects.update_or_create(
                defect=defect,
                receiver_id=pk,
                defaults={
                    "project": defect.project,
                    "created_by": request.user,
                    "sent_at": now,
                },
            )
        return Response(
            {
                "sent": len(eligible),
                "skipped": len(receivers) - len(eligible),
                "cooldown_seconds": 600,
            },
            status=201,
        )
