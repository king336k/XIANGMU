"""The DAQ reporting role has an explicit administrator-owned project list."""

import json
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from plane.db.models import Project
from plane.license.models import InstanceConfiguration
from .permissions import is_administrator
from .views import Conflict, QualityPagination

KEY = "QUALITY_DAQ_PROJECT_GRANTS"


def configuration(lock=False):
    query = InstanceConfiguration.objects.select_for_update() if lock else InstanceConfiguration.objects
    row = query.filter(key=KEY).first()
    return row, json.loads(row.value) if row else {"projects": [], "revision": 0}


def granted_projects():
    return configuration()[1]["projects"]


class GrantInput(serializers.Serializer):
    projects = serializers.ListField(child=serializers.UUIDField(), max_length=10000)
    expected_revision = serializers.IntegerField(min_value=0)


class DaqProjectGrants(BaseAPIView):
    def administrator(self, request):
        if not is_administrator(request.user):
            raise PermissionDenied("只有平台管理员可以给DAQ分配项目。")

    def get(self, request):
        self.administrator(request)
        _, state = configuration()
        query = Project.objects.filter(archived_at__isnull=True, workspace__deleted_at__isnull=True).order_by(
            "name", "id"
        )
        active_grants = list(map(str, query.filter(id__in=state["projects"]).values_list("id", flat=True)))
        search = serializers.CharField(max_length=200, allow_blank=True).run_validation(
            request.query_params.get("search", "")
        )
        if search:
            query = query.filter(Q(name__icontains=search) | Q(identifier__icontains=search))
        paginator = QualityPagination()
        page = paginator.paginate_queryset(query, request)
        response = paginator.get_paginated_response(
            [{"id": str(row.id), "name": row.name, "identifier": row.identifier} for row in page]
        )
        response.data.update(revision=state["revision"], projects=active_grants)
        response["Cache-Control"] = "no-store"
        return response

    @transaction.atomic
    def post(self, request):
        self.administrator(request)
        data = GrantInput(data=request.data)
        data.is_valid(raise_exception=True)
        data = data.validated_data
        from plane.license.models import Instance

        Instance.objects.select_for_update().get()
        _, state = configuration(lock=True)
        if state["revision"] != data["expected_revision"]:
            raise Conflict("DAQ项目授权已被修改，请刷新后再保存。")
        selected = set(map(str, data["projects"]))
        active = set(
            map(
                str,
                Project.objects.filter(
                    id__in=selected, archived_at__isnull=True, workspace__deleted_at__isnull=True
                ).values_list("id", flat=True),
            )
        )
        if selected != active:
            raise PermissionDenied("只能分配有效项目。")
        value = {"projects": sorted(selected), "revision": state["revision"] + 1, "updated_by": str(request.user.id)}
        InstanceConfiguration.objects.update_or_create(
            key=KEY,
            defaults={
                "value": json.dumps(value),
                "category": "DAQ_REPORTING",
            },
        )
        return Response(value)
