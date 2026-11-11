"""Read-only source snapshots remain distinct from local release readiness."""

from django.db import models
from .models import QualityRecord


class ExternalReleaseSnapshot(QualityRecord):
    source_instance = models.CharField(max_length=120)
    external_project_id = models.PositiveBigIntegerField()
    request_id = models.UUIDField()
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, default="preview")
    rows = models.JSONField(default=list)
    sha256 = models.CharField(max_length=64)
    confirmed_by = models.ForeignKey("db.User", on_delete=models.SET_NULL, null=True, related_name="+")
    confirmed_at = models.DateTimeField(null=True)

    class Meta(QualityRecord.Meta):
        constraints = [
            models.UniqueConstraint(fields=["project", "request_id"], name="quality_external_release_request_unique")
        ]
