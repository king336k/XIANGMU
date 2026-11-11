# SPDX-License-Identifier: AGPL-3.0-only
import re
import unicodedata
from collections import defaultdict
from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from .sharing_models import GovernanceDecision
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from plane.quality.permissions import knowledge_reviewer
from plane.quality.views import QualityView, Conflict
from .views import EditorialPermission
from .models import Article, ArticleEvent
from .serializers import ArticleSerializer


class MergeInput(serializers.Serializer):
    source_id = serializers.UUIDField()
    target_id = serializers.UUIDField()
    source_version = serializers.IntegerField(min_value=1)
    target_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=4000)


class ArticleVersion(serializers.Serializer):
    id = serializers.UUIDField()
    version = serializers.IntegerField(min_value=1)


class OfflineInput(serializers.Serializer):
    articles = ArticleVersion(many=True, allow_empty=False, max_length=100)
    reason = serializers.CharField(max_length=4000)


class Governance(QualityView):
    permission_classes = [EditorialPermission]

    def get(self, request, **kwargs):
        qs = Article.objects.filter(project=self.project())
        grouped = defaultdict(list)
        for article in qs.filter(merged_into__isnull=True).only("id", "title", "status", "edit_version")[:1000]:
            key = re.sub(r"\s+", "", unicodedata.normalize("NFKC", article.title)).casefold()
            grouped[key].append(
                {
                    "id": str(article.id),
                    "title": article.title,
                    "status": article.status,
                    "version": article.edit_version,
                }
            )
        return Response(
            {
                "total": qs.count(),
                "published": qs.filter(publication_active=True).count(),
                "review": qs.filter(status="review").count(),
                "merged": qs.filter(merged_into__isnull=False).count(),
                "candidates": [rows for rows in grouped.values() if len(rows) > 1],
                "semantic_candidates": semantic_candidates(
                    self.project(), request.query_params.get("semantic_threshold", "0.88")
                ),
                "merge_history": [
                    {
                        "id": str(row.id),
                        "source_title": row.source.title,
                        "target_title": row.target.title,
                        "created_at": row.created_at,
                        "can_undo": not row.undone
                        and row.source.edit_version == row.source_version
                        and row.target.edit_version == row.target_version,
                    }
                    for row in GovernanceDecision.objects.filter(project=self.project(), action="merge").select_related(
                        "source", "target"
                    )[:20]
                ],
                "scope": (
                    "同标题知识可选择两条比较后归并。检索仅使用当前有效发布版本；语义索引可由管理员或项目经理维护。"
                ),
            }
        )


class GovernanceMerge(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        if not knowledge_reviewer(self.project_id, request.user.id):
            raise PermissionDenied("只有当前项目有访问权限的管理员可以归并知识。")
        data = self.input(MergeInput)
        if data["source_id"] == data["target_id"]:
            raise ValidationError({"target_id": "请选择另一条目标知识。"})
        locked = {
            row.id: row
            for row in Article.objects.select_for_update()
            .filter(project=self.project(), id__in=[data["source_id"], data["target_id"]])
            .order_by("id")
        }
        source = locked.get(data["source_id"])
        target = locked.get(data["target_id"])
        if source is None or target is None:
            raise ValidationError({"error": "知识不存在或不属于当前项目。"})
        if source.edit_version != data["source_version"] or target.edit_version != data["target_version"]:
            raise Conflict()
        if source.merged_into_id or target.merged_into_id or source.status == "review" or target.status == "review":
            raise Conflict("请先完成或退回审核；已归并知识不能再次作为合并对象。")
        if len(target.content) + len(source.content) > 98000:
            raise ValidationError({"content": "合并后内容超过长度限制，请先编辑精简。"})
        target_snapshot = {key: getattr(target, key) for key in ["title", "content", "tags"]}
        if source.content.strip() != target.content.strip():
            target.content += "\n\n--- 归并来源：" + source.title + " ---\n" + source.content
        target.tags = list(dict.fromkeys([*target.tags, *source.tags]))[:20]
        target.status = "draft"
        target.edit_version += 1
        target.scanned_version = 0
        target.save()
        source.publication_active = False
        source.status = "offline"
        source.merged_into = target
        source.edit_version += 1
        source.save()
        GovernanceDecision.objects.create(
            project=source.project,
            created_by=request.user,
            source=source,
            target=target,
            source_version=source.edit_version,
            target_version=target.edit_version,
            action="merge",
            reason=data["reason"],
            snapshot={"target": target_snapshot},
        )
        for row in [source, target]:
            ArticleEvent.objects.create(
                project=row.project,
                article=row,
                created_by=request.user,
                action="merge",
                version=row.edit_version,
                note=f"{source.id} → {target.id}；{data['reason']}",
            )
        return Response(ArticleSerializer(target).data)


class GovernanceOffline(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        if not knowledge_reviewer(self.project_id, request.user.id):
            raise PermissionDenied("只有当前项目有访问权限的管理员可以下线知识。")
        data = self.input(OfflineInput)
        requested = {row["id"]: row["version"] for row in data["articles"]}
        rows = list(Article.objects.select_for_update().filter(project=self.project(), id__in=requested).order_by("id"))
        if len(rows) != len(requested):
            raise ValidationError({"articles": "知识不存在或不属于当前项目。"})
        if any(row.edit_version != requested[row.id] for row in rows):
            raise Conflict()
        if any(not row.publication_active for row in rows):
            raise Conflict("请选择仍在发布的知识；已下线条目不重复执行。")
        for row in rows:
            row.publication_active = False
            row.status = "offline"
            row.edit_version += 1
            row.save()
            ArticleEvent.objects.create(
                project=row.project,
                article=row,
                created_by=request.user,
                action="offline",
                version=row.edit_version,
                note=data["reason"],
            )
        return Response({"count": len(rows)})


def semantic_candidates(project, threshold):
    from .semantic import content_hash
    from .semantic_models import SemanticRevisionIndex
    from . import semantic_provider
    from .semantic_vectors import normalized_vector

    value = serializers.FloatField(min_value=0.5, max_value=1.0).run_validation(threshold)
    config = semantic_provider.configuration(project.workspace_id)
    if not config["configured"]:
        return []
    vectors = list(
        SemanticRevisionIndex.objects.filter(
            project=project,
            fingerprint=config["fingerprint"],
            revision__article__project=project,
            revision__article__publication_active=True,
            revision__version=F("revision__article__published_version"),
            revision__article__merged_into__isnull=True,
        )
        .select_related("revision__article")
        .order_by("revision__article_id")[:128]
    )
    rows = []
    for row in vectors:
        if not row.vectors or row.content_hash != content_hash(row.revision):
            continue
        try:
            if not all(len(part) == len(row.vectors[0]) for part in row.vectors):
                continue
            row.summary_vector = normalized_vector([sum(axis) / len(row.vectors) for axis in zip(*row.vectors)])
        except (ValueError, TypeError, ZeroDivisionError):
            continue
        rows.append(row)
    ignored = {
        (str(d.source_id), str(d.target_id), d.source_version, d.target_version)
        for d in GovernanceDecision.objects.filter(project=project, action="ignore")
    }
    candidates = []

    def info(article):
        return {
            "id": str(article.id),
            "title": article.title,
            "version": article.edit_version,
            "status": article.status,
        }

    for index, left in enumerate(rows):
        for right in rows[index + 1 :]:
            a, b = left.revision.article, right.revision.article
            if (
                a.id == b.id
                or (str(a.id), str(b.id), a.edit_version, b.edit_version) in ignored
                or (str(b.id), str(a.id), b.edit_version, a.edit_version) in ignored
            ):
                continue
            try:
                score = sum(x * y for x, y in zip(left.summary_vector, right.summary_vector))
            except (ValueError, TypeError):
                continue
            if score >= value:
                candidates.append(
                    {
                        "source": info(a),
                        "target": info(b),
                        "similarity": round(score, 4),
                        "basis": "当前发布正文向量均值的相似度，需核对适用场景",
                        "threshold": value,
                    }
                )
    return sorted(candidates, key=lambda row: -row["similarity"])[:50]


class GovernanceIgnore(QualityView):
    @transaction.atomic
    def post(self, request, **kwargs):
        if not knowledge_reviewer(self.project_id, request.user.id):
            raise PermissionDenied("当前角色不能保留不同知识。")
        data = self.input(MergeInput)
        if data["source_id"] == data["target_id"]:
            raise ValidationError({"target_id": "请选择不同知识。"})
        rows = {
            row.id: row
            for row in Article.objects.select_for_update()
            .filter(project=self.project(), pk__in=[data["source_id"], data["target_id"]])
            .order_by("id")
        }
        a, b = rows.get(data["source_id"]), rows.get(data["target_id"])
        if not a or not b:
            raise ValidationError({"error": "知识不存在或不属于本项目。"})
        if a.edit_version != data["source_version"] or b.edit_version != data["target_version"]:
            raise Conflict()
        decision = GovernanceDecision.objects.filter(
            project=a.project,
            source=a,
            target=b,
            source_version=a.edit_version,
            target_version=b.edit_version,
            action="ignore",
        ).first()
        if not decision:
            decision = GovernanceDecision.objects.create(
                project=a.project,
                created_by=request.user,
                source=a,
                target=b,
                source_version=a.edit_version,
                target_version=b.edit_version,
                action="ignore",
                reason=data["reason"],
            )
        return Response({"id": str(decision.id)}, status=201)


class GovernanceUndo(QualityView):
    @transaction.atomic
    def post(self, request, pk, **kwargs):
        if not knowledge_reviewer(self.project_id, request.user.id):
            raise PermissionDenied("当前角色不能撤回归并。")
        reason = serializers.CharField(max_length=4000).run_validation(request.data.get("reason", ""))
        decision = get_object_or_404(
            GovernanceDecision.objects.select_for_update(), pk=pk, project_id=self.project_id, action="merge"
        )
        locked = {
            row.id: row
            for row in Article.objects.select_for_update()
            .filter(project=self.project(), pk__in=[decision.source_id, decision.target_id])
            .order_by("id")
        }
        source, target = locked[decision.source_id], locked[decision.target_id]
        if decision.undone:
            return Response({"id": str(decision.id), "undone": True})
        if (
            source.edit_version != decision.source_version
            or target.edit_version != decision.target_version
            or source.merged_into_id != target.id
        ):
            raise Conflict("归并后已有其他修改，请逐条核对，不能覆盖后续内容。")
        for key in ["title", "content", "tags"]:
            setattr(target, key, decision.snapshot["target"][key])
        source.merged_into = None
        for row in [source, target]:
            row.edit_version += 1
            row.status = "draft"
            row.publication_active = False
            row.scanned_version = 0
            row.save()
            ArticleEvent.objects.create(
                project=row.project,
                article=row,
                created_by=request.user,
                action="undo_merge",
                version=row.edit_version,
                note=reason,
            )
        decision.undone = True
        decision.save(update_fields=["undone"])
        return Response({"id": str(decision.id), "undone": True})
