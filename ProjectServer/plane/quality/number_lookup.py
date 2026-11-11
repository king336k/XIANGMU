"""Resolve a public number only within the caller's active project memberships."""

from django.apps import apps
from rest_framework import serializers
from rest_framework.response import Response
from plane.app.views.base import BaseAPIView
from .models import BusinessNumber
from .permissions import capable

DESTINATIONS = {
    "defect": ("缺陷", "defects", "defect"),
    "testcase": ("用例", "quality", "case"),
    "testplan": ("测试计划", "quality", "plan"),
    "testsuite": ("用例集", "quality", "suites"),
    "testexecution": ("执行记录", "quality", "executions"),
    "release": ("版本准入", "quality", "releases"),
    "projectversion": ("版本迭代", "versions", "version"),
    "article": ("知识", "knowledge", "articles"),
}


class NumberLookup(BaseAPIView):
    def get(self, request, **kwargs):
        code = serializers.CharField(max_length=96).run_validation(request.query_params.get("code", ""))
        rows = (
            BusinessNumber.objects.filter(
                code__iexact=code,
                project__workspace__slug=request.query_params.get("workspace"),
                project__archived_at__isnull=True,
                project__project_projectmember__member=request.user,
                project__project_projectmember__is_active=True,
                project__project_projectmember__role__gte=15,
                project__workspace__workspace_member__member=request.user,
                project__workspace__workspace_member__is_active=True,
                project__workspace__workspace_member__role__gte=15,
            )
            .select_related("project")
            .distinct()[:20]
        )
        results = []
        for reference in rows:
            model = apps.get_model(reference.resource)
            kind = model._meta.model_name
            if kind not in DESTINATIONS:
                continue
            if kind == "article" and not capable(reference.project_id, request.user.id, "knowledge_edit"):
                continue
            row = model.objects.filter(pk=reference.object_id, project_id=reference.project_id).first()
            if not row or any(getattr(row, key, None) for key in ["trashed_at", "archived_at"]):
                continue
            label, path, target = DESTINATIONS[kind]
            query = (
                f"{target}={row.pk}"
                if target in {"defect", "plan", "version", "case"}
                else f"tab={target}&search={reference.code}"
            )
            if kind == "testplan":
                query = "tab=plans&" + query
            url = f"/{reference.project.workspace.slug}/p/{reference.project.identifier}/{path}/?{query}"
            results.append(
                {
                    "id": str(row.pk),
                    "code": reference.code,
                    "name": getattr(row, "title", getattr(row, "name", "")),
                    "kind": label,
                    "url": url,
                }
            )
        return Response({"results": results})
