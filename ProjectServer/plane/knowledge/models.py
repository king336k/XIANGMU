# SPDX-License-Identifier: AGPL-3.0-only
from django.db import models
from plane.quality.models import QualityRecord


class Article(QualityRecord):
    source_defect = models.ForeignKey(
        "quality.Defect", on_delete=models.PROTECT, null=True, blank=True, related_name="knowledge_articles"
    )
    source_regression = models.ForeignKey(
        "quality.DataRegression", on_delete=models.PROTECT, null=True, blank=True, related_name="knowledge_articles"
    )
    merged_into = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="merged_sources"
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    tags = models.JSONField(default=list)
    status = models.CharField(max_length=16, default="draft")
    edit_version = models.PositiveIntegerField(default=1)
    published_version = models.PositiveIntegerField(default=0)
    publication_active = models.BooleanField(default=False)
    scanned_version = models.PositiveIntegerField(default=0)
    scan_findings = models.JSONField(default=list)
    source_issue = models.ForeignKey(
        "db.Issue", on_delete=models.PROTECT, null=True, blank=True, related_name="knowledge_articles"
    )
    updated_at = models.DateTimeField(auto_now=True)


class PublishedRevision(QualityRecord):
    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    content = models.TextField()
    tags = models.JSONField(default=list)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["article", "version"], name="knowledge_publication_unique")]


class ArticleEvent(QualityRecord):
    article = models.ForeignKey(Article, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=16)
    version = models.PositiveIntegerField()
    note = models.TextField(blank=True)


class Conversation(QualityRecord):
    title = models.CharField(max_length=160)


class ChatMessage(QualityRecord):
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name="messages")
    request_id = models.UUIDField()
    query = models.CharField(max_length=2000)
    status = models.CharField(max_length=20, default="running")
    answer = models.TextField(blank=True)
    suggested_actions = models.JSONField(default=list)
    verification_steps = models.JSONField(default=list)
    citations = models.JSONField(default=list)
    error_code = models.CharField(max_length=32, blank=True)
    feedback = models.CharField(max_length=16, blank=True)
    feedback_note = models.CharField(max_length=2000, blank=True)
    model = models.CharField(max_length=120, blank=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_id"], name="knowledge_chat_request_unique"
            )
        ]


# Register optional semantic cache models without mixing them into editorial records.
from .semantic_models import SemanticProjectIndex, SemanticRevisionIndex  # noqa: F401,E402

from .sharing_models import KnowledgeShare, GovernanceDecision  # noqa: F401,E402
