"""Explicit project-to-project grants bind to one immutable knowledge revision."""

from django.db import models
from plane.quality.models import QualityRecord


class KnowledgeShare(QualityRecord):
    article = models.ForeignKey("knowledge.Article", on_delete=models.PROTECT, related_name="shares")
    revision = models.ForeignKey("knowledge.PublishedRevision", on_delete=models.PROTECT, related_name="shares")
    target_project = models.ForeignKey("db.Project", on_delete=models.PROTECT, related_name="incoming_knowledge_shares")
    active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    reason = models.CharField(max_length=4000)
    device_scope = models.CharField(max_length=255, blank=True)
    version_scope = models.CharField(max_length=255, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["article", "target_project"], name="knowledge_share_target_unique")
        ]


class GovernanceDecision(QualityRecord):
    source = models.ForeignKey(
        "knowledge.Article", on_delete=models.PROTECT, related_name="source_governance_decisions"
    )
    target = models.ForeignKey(
        "knowledge.Article", on_delete=models.PROTECT, related_name="target_governance_decisions"
    )
    source_version = models.PositiveIntegerField()
    target_version = models.PositiveIntegerField()
    action = models.CharField(max_length=16)
    reason = models.CharField(max_length=4000)
    snapshot = models.JSONField(default=dict)
    undone = models.BooleanField(default=False)
