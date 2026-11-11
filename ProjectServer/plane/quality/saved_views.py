# SPDX-License-Identifier: AGPL-3.0-only
import json
from django.db import transaction
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from plane.db.models import WorkspaceMember, ProjectMember
from .models import (
    SavedQualityView,
    Defect,
    TestCase,
    TestPlan,
    TestExecution,
    TestSuite,
    Release,
    Requirement,
    SavedReport,
)
from .views import QualityView, Conflict
from .filters import SPECS, filter_records


def resources():
    from plane.knowledge.models import Article

    return {
        "defects": Defect,
        "cases": TestCase,
        "plans": TestPlan,
        "executions": TestExecution,
        "suites": TestSuite,
        "releases": Release,
        "requirements": Requirement,
        "reports": SavedReport,
        "articles": Article,
    }


class PersonalViewPermission(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and WorkspaceMember.objects.filter(
                workspace__slug=view.workspace_slug, member=request.user, is_active=True
            ).exists()
            and ProjectMember.objects.filter(
                project_id=view.project_id,
                workspace__slug=view.workspace_slug,
                member=request.user,
                is_active=True,
                project__archived_at__isnull=True,
            ).exists()
        )


class SavedInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    resource = serializers.ChoiceField(
        choices=["defects", "cases", "plans", "executions", "suites", "releases", "requirements", "reports", "articles"]
    )
    filters = serializers.DictField(child=serializers.CharField(max_length=255), allow_empty=True)


class SavedSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedQualityView
        fields = ["id", "name", "resource", "filters", "created_at"]


class SavedViews(QualityView):
    permission_classes = [PersonalViewPermission]

    def get(self, request, **kwargs):
        resource = request.query_params.get("resource", "defects")
        if resource not in resources():
            raise ValidationError({"resource": "无效的模块。"})
        qs = SavedQualityView.objects.filter(
            project=self.project(), created_by=request.user, resource=resource, active=True
        )
        return Response(SavedSerializer(qs, many=True).data)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(SavedInput)
        model = resources()[data["resource"]]
        allowed = set(SPECS[model._meta.model_name]) | {
            "created_by_id",
            "created_after",
            "created_before",
            "view",
            "ordering",
            "layout",
        }
        if data["resource"] in {"cases", "plans", "suites", "defects"}:
            allowed.add("archived")
        if set(data["filters"]) - allowed or len(json.dumps(data["filters"]).encode()) > 4096:
            raise ValidationError({"filters": "只保存当前模块支持的查询条件，不接受地址、项目或任意表达式。"})
        if data["filters"].get("layout", "list") not in ["list", "table", "board"]:
            raise ValidationError({"filters": "仅支持列表、表格或看板显示。"})
        query = QueryDict("", mutable=True)
        query.update(data["filters"])
        filter_records(model.objects.none(), query, request.user)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        prior = SavedQualityView.objects.filter(
            project=project, created_by=request.user, resource=data["resource"], name=data["name"]
        ).first()
        if prior:
            if prior.active:
                raise Conflict("同名个人视图已存在，请使用不同名称。")
            prior.active = True
            prior.filters = data["filters"]
            prior.save()
            return Response(SavedSerializer(prior).data, status=201)
        if (
            SavedQualityView.objects.filter(
                project=project, created_by=request.user, resource=data["resource"], active=True
            ).count()
            >= 50
        ):
            raise ValidationError({"name": "每个模块最多保存50个个人视图，请先移除不再使用的视图。"})
        row = SavedQualityView.objects.create(project=project, created_by=request.user, **data)
        return Response(SavedSerializer(row).data, status=201)


class SavedViewDetail(QualityView):
    permission_classes = [PersonalViewPermission]

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        class RenameInput(serializers.Serializer):
            name = serializers.CharField(max_length=120)
            expected_name = serializers.CharField(max_length=120)

        data = self.input(RenameInput)
        project = self.project()
        type(project).objects.select_for_update().get(pk=project.pk)
        row = get_object_or_404(
            SavedQualityView.objects.select_for_update(), pk=pk, project=project, created_by=request.user, active=True
        )
        if row.name != data["expected_name"]:
            raise Conflict("视图名称已改变，请刷新后重试。")
        if (
            SavedQualityView.objects.filter(
                project=project, created_by=request.user, resource=row.resource, name=data["name"]
            )
            .exclude(pk=row.pk)
            .exists()
        ):
            raise Conflict("同名个人视图已存在，请使用不同名称。")
        row.name = data["name"]
        row.save(update_fields=["name"])
        return Response(SavedSerializer(row).data)

    @transaction.atomic
    def delete(self, request, pk, **kwargs):
        row = get_object_or_404(
            SavedQualityView.objects.select_for_update(),
            pk=pk,
            project_id=self.project_id,
            created_by=request.user,
            active=True,
        )
        row.active = False
        row.save(update_fields=["active"])
        return Response(status=204)
