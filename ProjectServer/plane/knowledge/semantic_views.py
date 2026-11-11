"""Explicit project administrator consent before any published knowledge is embedded."""

from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.permissions import SAFE_METHODS
from plane.quality.views import QualityView, QualityPermission
from plane.quality.permissions import knowledge_reviewer
from . import semantic, semantic_provider
from .retrieval import published
from .semantic_models import SemanticProjectIndex, SemanticRevisionIndex


class IndexInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=["build"])


class SemanticIndexPermission(QualityPermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return super().has_permission(request, view)
        return request.user.is_authenticated and knowledge_reviewer(view.project_id, request.user.id)


class SemanticIndexView(QualityView):
    permission_classes = [SemanticIndexPermission]

    def get(self, request, **kwargs):
        project = self.project()
        config = semantic_provider.configuration(project.workspace_id)
        info = semantic_provider.public_status(config)
        job = SemanticProjectIndex.objects.filter(project=project, fingerprint=config["fingerprint"]).first()
        count = SemanticRevisionIndex.objects.filter(
            revision__in=published(project), fingerprint=config["fingerprint"]
        ).count()
        return Response(
            {
                **info,
                "status": job.status
                if config["configured"] and job
                else "idle"
                if config["configured"]
                else info["status"],
                "indexed_count": count,
                "eligible_count": published(project).count(),
                "can_build": knowledge_reviewer(project.id, request.user.id),
                "error_code": job.error_code if job else "",
            }
        )

    def post(self, request, **kwargs):
        self.input(IndexInput)
        project = self.project()
        if not knowledge_reviewer(project.id, request.user.id):
            raise PermissionDenied("只有当前项目知识审核管理员可以建立语义索引。")
        try:
            job = semantic.request_build(project, request.user)
        except ValueError:
            raise ValidationError({"error": "请先启用语义检索并配置可用的向量模型。"})
        transaction.on_commit(lambda: semantic.enqueue(project.id, job.token))
        response = self.get(request, **kwargs)
        response.status_code = 202
        return response
