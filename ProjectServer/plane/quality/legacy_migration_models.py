"""Offline migration audit only; these records grant no runtime permissions."""

import uuid
from django.conf import settings
from django.db import models


class LegacyMigrationRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_key = models.CharField(max_length=255, unique=True)
    manifest_hash = models.CharField(max_length=64)
    mapping_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default="applied")
    summary = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    rolled_back_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "quality"


class LegacyMigrationRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(LegacyMigrationRun, on_delete=models.PROTECT, related_name="records")
    source_table = models.CharField(max_length=80)
    source_id = models.CharField(max_length=255)
    source_hash = models.CharField(max_length=64)
    source_snapshot = models.JSONField(default=dict)
    disposition = models.CharField(max_length=24)
    targets = models.JSONField(default=list)

    class Meta:
        app_label = "quality"
        constraints = [
            models.UniqueConstraint(fields=["run", "source_table", "source_id"], name="quality_legacy_source_unique")
        ]
