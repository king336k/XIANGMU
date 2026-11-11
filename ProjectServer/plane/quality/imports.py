# SPDX-License-Identifier: AGPL-3.0-only
import json
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import override
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from plane.db.models import Issue
from .models import CaseImport, TestCase
from .serializers import CaseInput
from .views import QualityView, add_revision


class ImportInput(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    cases = serializers.ListField(child=serializers.DictField(), allow_empty=False, max_length=500)

    def validate_cases(self, rows):
        if len(JSONRenderer().render(rows)) > 2 * 1024 * 1024:
            raise serializers.ValidationError("导入内容不能超过2MB。")
        return rows


class ImportSerializer(serializers.ModelSerializer):
    valid = serializers.SerializerMethodField()
    case_count = serializers.SerializerMethodField()

    def get_valid(self, obj):
        return not obj.errors

    def get_case_count(self, obj):
        return len(obj.rows)

    class Meta:
        model = CaseImport
        fields = [
            "id",
            "name",
            "status",
            "valid",
            "case_count",
            "rows",
            "errors",
            "case_ids",
            "created_at",
            "confirmed_at",
        ]


def validate_rows(rows, project_id):
    errors, normalized = [], []
    for index, row in enumerate(rows, 1):
        # A preview is a new case import, never an update of an existing revision.
        unknown = set(row) - (set(CaseInput().fields) - {"expected_version"})
        serializer = CaseInput(data=row)
        with override("zh-hans"):
            valid = serializer.is_valid()
        if unknown:
            errors.append({"row": index, "fields": {"unknown": ["包含不支持的字段：" + ", ".join(sorted(unknown))]}})
        elif not valid:
            errors.append({"row": index, "fields": serializer.errors})
        else:
            data = serializer.validated_data
            requirement_id = data.get("requirement_id")
            if requirement_id and not Issue.objects.filter(pk=requirement_id, project_id=project_id).exists():
                errors.append({"row": index, "fields": {"requirement_id": ["需求不存在或不属于当前项目。"]}})
            else:
                normalized.append(data)
    return errors, normalized


class ImportList(QualityView):
    def get(self, request, **kwargs):
        return self.listing(CaseImport.objects.filter(project=self.project()), ImportSerializer)

    def post(self, request, **kwargs):
        data = self.input(ImportInput)
        errors, normalized = validate_rows(data["cases"], self.project_id)
        preview = CaseImport.objects.create(
            project=self.project(),
            created_by=request.user,
            name=data["name"],
            rows=json.loads(JSONRenderer().render(data["cases"])),
            errors=errors,
        )
        return Response(ImportSerializer(preview).data)


class ImportConfirm(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        preview = get_object_or_404(CaseImport.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if preview.status == "confirmed":
            return Response(ImportSerializer(preview).data)
        errors, rows = validate_rows(preview.rows, self.project_id)
        if errors:
            raise ValidationError({"error": "预检未通过，请修正原文件并重新导入。", "rows": errors})
        ids = []
        for row in rows:
            case = TestCase.objects.create(project=preview.project, created_by=request.user, **row)
            add_revision(case, request.user)
            ids.append(str(case.pk))
        preview.status = "confirmed"
        preview.case_ids = ids
        preview.confirmed_at = timezone.now()
        preview.save(update_fields=["status", "case_ids", "confirmed_at"])
        return Response(ImportSerializer(preview).data)
