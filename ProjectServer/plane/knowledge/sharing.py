"""Managers explicitly authorize frozen publications for another managed project."""

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import Project
from plane.quality.permissions import knowledge_reviewer
from plane.quality.views import QualityView, QualityPagination, Conflict
from .models import Article, ArticleEvent, PublishedRevision
from .sharing_models import KnowledgeShare


class ShareInput(serializers.Serializer):
    target_project_id = serializers.UUIDField()
    expected_version = serializers.IntegerField(min_value=1)
    expected_share_version = serializers.IntegerField(min_value=1, required=False)
    reason = serializers.CharField(max_length=4000)
    device_scope = serializers.CharField(max_length=255, allow_blank=True, default="")
    version_scope = serializers.CharField(max_length=255, allow_blank=True, default="")


class WithdrawInput(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=4000)


def require_manager(project_id, actor):
    if not knowledge_reviewer(project_id, actor.id):
        raise PermissionDenied("只有管理员或项目经理可以授权或撤回共享知识。")


def share_data(row):
    return {
        "id": str(row.id),
        "target_project_id": str(row.target_project_id),
        "target_project_name": row.target_project.name,
        "publication_version": row.revision.version,
        "active": row.active,
        "effective": bool(
            row.active
            and row.article.publication_active
            and row.article.published_version == row.revision.version
            and not row.target_project.archived_at
        ),
        "version": row.version,
        "device_scope": row.device_scope,
        "version_scope": row.version_scope,
        "reason": row.reason,
    }


class ShareTargets(QualityView):
    def get(self, request, **kwargs):
        source = self.project()
        require_manager(source.id, request.user)
        query = (
            Project.objects.filter(
                workspace=source.workspace,
                archived_at__isnull=True,
                project_projectmember__member=request.user,
                project_projectmember__is_active=True,
                project_projectmember__role__gte=15,
            )
            .exclude(pk=source.id)
            .distinct()
        )
        query = query.filter(pk__in=[p.id for p in query if knowledge_reviewer(p.id, request.user.id)])
        search = serializers.CharField(max_length=160, allow_blank=True).run_validation(
            request.query_params.get("search", "")
        )
        if search:
            query = query.filter(Q(name__icontains=search) | Q(identifier__icontains=search))
        pager = QualityPagination()
        rows = pager.paginate_queryset(query.order_by("name", "id"), request)
        return pager.get_paginated_response(
            [{"id": str(p.id), "name": p.name, "identifier": p.identifier} for p in rows]
        )


class ArticleShares(QualityView):
    def get(self, request, pk, **kwargs):
        require_manager(self.project_id, request.user)
        article = self.obj(Article, pk)
        pager = QualityPagination()
        rows = pager.paginate_queryset(
            KnowledgeShare.objects.filter(article=article).select_related("target_project", "revision", "article"),
            request,
        )
        return pager.get_paginated_response([share_data(row) for row in rows])

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        require_manager(self.project_id, request.user)
        data = self.input(ShareInput)
        article = get_object_or_404(Article.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if article.edit_version != data["expected_version"]:
            raise Conflict()
        if not article.publication_active or article.merged_into_id:
            raise Conflict("请先发布有效知识，再设置共享。")
        target = get_object_or_404(
            Project, pk=data["target_project_id"], workspace=article.project.workspace, archived_at__isnull=True
        )
        if target.id == article.project_id:
            raise ValidationError({"target_project_id": "本项目知识无需重复共享。"})
        require_manager(target.id, request.user)
        revision = get_object_or_404(
            PublishedRevision, article=article, project=article.project, version=article.published_version
        )
        row, created = KnowledgeShare.objects.select_for_update().get_or_create(
            article=article,
            target_project=target,
            defaults={
                "project": article.project,
                "revision": revision,
                "created_by": request.user,
                "reason": data["reason"],
                "device_scope": data["device_scope"],
                "version_scope": data["version_scope"],
            },
        )
        if not created and row.active:
            if (
                row.revision_id == revision.id
                and row.reason == data["reason"]
                and row.device_scope == data["device_scope"]
                and row.version_scope == data["version_scope"]
            ):
                return Response(share_data(row))
            raise Conflict("此项目已有共享授权，请先撤回后重新设置范围。")
        if not created and data.get("expected_share_version") != row.version:
            raise Conflict("共享范围已经变更，请刷新后明确重新授权。")
        if not created:
            row.revision = revision
            row.active = True
            row.version += 1
            row.reason = data["reason"]
            row.device_scope = data["device_scope"]
            row.version_scope = data["version_scope"]
            row.withdrawn_at = None
            row.withdrawn_by = None
            row.save()
        ArticleEvent.objects.create(
            article=article,
            project=article.project,
            created_by=request.user,
            action="share",
            version=article.edit_version,
            note=f"共享发布 v{revision.version} 至 {target.identifier}：{data['reason']}",
        )
        response = Response(share_data(row), status=201 if created else 200)
        response["Cache-Control"] = "no-store"
        return response


class ShareWithdraw(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        require_manager(self.project_id, request.user)
        data = self.input(WithdrawInput)
        row = get_object_or_404(
            KnowledgeShare.objects.select_for_update().select_related("article", "revision", "target_project"),
            pk=pk,
            project_id=self.project_id,
        )
        if row.version != data["expected_version"]:
            raise Conflict()
        row.active = False
        row.version += 1
        row.withdrawn_at = timezone.now()
        row.withdrawn_by = request.user
        row.reason = data["reason"]
        row.save()
        ArticleEvent.objects.create(
            article=row.article,
            project=row.project,
            created_by=request.user,
            action="withdraw_share",
            version=row.article.edit_version,
            note=f"撤回 {row.target_project.identifier} 的共享：{data['reason']}",
        )
        return Response(share_data(row))
