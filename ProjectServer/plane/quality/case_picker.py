# SPDX-License-Identifier: AGPL-3.0-only
from django.db.models import Count
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .models import TestCase
from .filters import filter_records
from .views import QualityView, QualityPagination
from .authorship import AuthoredRecordSerializer
from .numbering import preload


class CaseOptionSerializer(AuthoredRecordSerializer):
    class Meta:
        model = TestCase
        fields = ["id", "title", "module", "priority", "version", "requirement_title"]

    requirement_title = serializers.CharField(source="requirement.name", default=None, read_only=True)


class CaseOptions(QualityView):
    def get(self, request, **kwargs):
        all_cases = TestCase.objects.filter(project=self.project(), archived_at__isnull=True, trashed_at__isnull=True)
        modules = list(all_cases.values("module").annotate(count=Count("id")).order_by("module"))
        # Archived records are never selectable, even if a caller supplies archived=true.
        params = request.query_params.copy()
        params["archived"] = "false"
        if serializers.BooleanField().run_validation(params.get("module_empty", False)):
            all_cases = all_cases.filter(module="")
            params.pop("module", None)
        cases = filter_records(all_cases, params, request.user).select_related("requirement").order_by("title", "id")
        if serializers.BooleanField().run_validation(params.get("selection", False)):
            count = cases.count()
            if count > 500:
                raise ValidationError({"selection": "单个计划或套件最多选择500条用例，请按模块或优先级缩小筛选范围。"})
            rows = list(cases)
            preload(rows)
            return Response({"count": count, "results": CaseOptionSerializer(rows, many=True).data})
        paginator = QualityPagination()
        rows = paginator.paginate_queryset(cases, request)
        preload(rows)
        response = paginator.get_paginated_response(CaseOptionSerializer(rows, many=True).data)
        response.data["modules"] = modules
        return response
