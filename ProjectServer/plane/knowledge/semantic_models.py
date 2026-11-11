"""Optional project opt-in and version-bound embedding cache; no source text or credentials."""

from django.db import models
from plane.quality.models import QualityRecord


class SemanticProjectIndex(QualityRecord):
    fingerprint = models.CharField(max_length=64)
    token = models.UUIDField()
    snapshot_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default="queued")
    error_code = models.CharField(max_length=40, blank=True)
    started_at = models.DateTimeField(null=True)

    class Meta(QualityRecord.Meta):
        constraints = [models.UniqueConstraint(fields=["project"], name="knowledge_semantic_project_unique")]


class SemanticRevisionIndex(QualityRecord):
    revision = models.ForeignKey(
        "knowledge.PublishedRevision", on_delete=models.CASCADE, related_name="semantic_indexes"
    )
    fingerprint = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    vectors = models.JSONField(default=list)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["revision", "fingerprint"], name="knowledge_semantic_revision_unique")
        ]
