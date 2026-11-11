# SPDX-License-Identifier: AGPL-3.0-only
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.db.models import ProjectMember, WorkspaceMember
from plane.quality.permissions import capable, knowledge_reviewer
from plane.quality.views import Conflict, QualityView, QualityPermission
from plane.authentication.session import BaseSessionAuthentication
from plane.quality.identity import PlatformBridgeAuthentication
from .models import Article, ArticleEvent, PublishedRevision
from .serializers import ArticleInput, ArticleSerializer, PublicationSerializer
from .retrieval import search, scan_article


def article_queryset():
    return Article.objects.prefetch_related("versions", "events__created_by")


class EditorialPermission(QualityPermission):
    def has_permission(self, request, view):
        return (
            super().has_permission(request, view)
            and capable(view.project_id, request.user.id, "knowledge_edit")
            and ProjectMember.objects.filter(
                project_id=view.project_id, member=request.user, is_active=True, role__gte=15
            ).exists()
            and WorkspaceMember.objects.filter(
                workspace__slug=view.workspace_slug, member=request.user, is_active=True, role__gte=15
            ).exists()
        )


class ArticleList(QualityView):
    permission_classes = [EditorialPermission]

    def get(self, request, **kwargs):
        return self.listing(article_queryset().filter(project=self.project()), ArticleSerializer)

    @transaction.atomic
    def post(self, request, **kwargs):
        data = self.input(ArticleInput)
        data.pop("expected_version", None)
        self.validate_issue(data.get("source_issue_id"))
        article = Article.objects.create(project=self.project(), created_by=request.user, **data)
        return Response(ArticleSerializer(article).data, status=201)


class ArticleDetail(QualityView):
    permission_classes = [EditorialPermission]

    def get(self, request, pk, **kwargs):
        return Response(
            ArticleSerializer(get_object_or_404(article_queryset(), pk=pk, project_id=self.project_id)).data
        )

    @transaction.atomic
    def patch(self, request, pk, **kwargs):
        data = self.input(ArticleInput, partial=True)
        article = get_object_or_404(Article.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data.pop("expected_version", None) != article.edit_version:
            raise Conflict()
        if article.merged_into_id:
            raise Conflict("此知识已归并，请维护目标知识，历史版本仍可查看。")
        if article.status == "review":
            raise Conflict("知识正在审核，请先退回后修改。")
        self.validate_issue(data.get("source_issue_id"))
        for key, value in data.items():
            setattr(article, key, value)
        article.edit_version += 1
        article.status = "draft"
        article.save()
        ArticleEvent.objects.create(
            article=article,
            project=article.project,
            created_by=request.user,
            action="edit",
            version=article.edit_version,
        )
        return Response(ArticleSerializer(article_queryset().get(pk=article.pk)).data)


class KnowledgeActionInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=["scan", "submit", "publish", "reject", "offline"])
    expected_version = serializers.IntegerField(min_value=1)
    comment = serializers.CharField(max_length=4000, allow_blank=True, default="")


class ArticleWorkflow(QualityView):
    permission_classes = [EditorialPermission]

    @transaction.atomic
    def post(self, request, pk, **kwargs):
        data = self.input(KnowledgeActionInput)
        article = get_object_or_404(Article.objects.select_for_update(), pk=pk, project_id=self.project_id)
        if data["expected_version"] != article.edit_version:
            raise Conflict()
        if article.merged_into_id:
            raise Conflict("此知识已归并，不能重新发布为重复条目。")
        action = data["action"]
        if action in {"publish", "reject", "offline"} and not knowledge_reviewer(self.project_id, request.user.id):
            raise PermissionDenied("只有当前项目有访问权限的管理员可以审核、发布或下线知识。")
        if action == "scan":
            if article.status != "draft":
                raise Conflict("请在草稿状态扫描。")
            article.scan_findings = scan_article(article.title, article.content, article.tags)
            article.scanned_version = article.edit_version + 1
        elif action == "submit":
            if article.status != "draft":
                raise Conflict("当前版本不是可提交的草稿。")
            if article.scanned_version != article.edit_version or article.scan_findings:
                raise ValidationError({"error": "请先完成当前版本的脱敏扫描，并修正全部疑似敏感信息。"})
            article.status = "review"
        elif action == "publish":
            if article.status not in {"draft", "review"}:
                raise Conflict("请先编辑并检查新的草稿。")
            if article.status == "draft" and (article.scanned_version != article.edit_version or article.scan_findings):
                raise ValidationError({"error": "请先完成当前版本的脱敏检查，并处理发现的问题。"})
            article.published_version += 1
            PublishedRevision.objects.create(
                article=article,
                project=article.project,
                created_by=request.user,
                version=article.published_version,
                title=article.title,
                content=article.content,
                tags=article.tags,
            )
            article.status = "published"
            article.publication_active = True
            from .base_knowledge import sync_base_publication

            sync_base_publication(article)
            from .semantic import schedule_if_opted_in

            transaction.on_commit(lambda: schedule_if_opted_in(article.project))
        elif action == "reject":
            if article.status != "review" or not data["comment"].strip():
                raise ValidationError({"error": "只能退回待审核版本，并须填写原因。"})
            article.status = "draft"
            article.scanned_version = 0
        elif action == "offline":
            if not article.publication_active or not data["comment"].strip():
                raise ValidationError({"error": "下线已发布知识需要填写原因。"})
            article.publication_active = False
            article.status = "offline"
        article.edit_version += 1
        article.save()
        ArticleEvent.objects.create(
            article=article,
            project=article.project,
            created_by=request.user,
            action=action,
            version=article.edit_version,
            note=data["comment"],
        )
        return Response(ArticleSerializer(article_queryset().get(pk=article.pk)).data)


class KnowledgeSearch(QualityView):
    authentication_classes = [PlatformBridgeAuthentication, BaseSessionAuthentication]

    def get(self, request, **kwargs):
        query = request.query_params.get("q", "")[:2000]
        return self.listing(search(self.project(), query), PublicationSerializer)
