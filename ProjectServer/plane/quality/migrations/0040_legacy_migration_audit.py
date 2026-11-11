import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0039_multiple_platform_projects"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="LegacyMigrationRun",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("source_key", models.CharField(max_length=255, unique=True)),
                ("manifest_hash", models.CharField(max_length=64)),
                ("mapping_hash", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=24, default="applied")),
                ("summary", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("rolled_back_at", models.DateTimeField(null=True)),
                (
                    "created_by",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
        migrations.CreateModel(
            name="LegacyMigrationRecord",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("source_table", models.CharField(max_length=80)),
                ("source_id", models.CharField(max_length=255)),
                ("source_hash", models.CharField(max_length=64)),
                ("source_snapshot", models.JSONField(default=dict)),
                ("disposition", models.CharField(max_length=24)),
                ("targets", models.JSONField(default=list)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="records",
                        to="quality.legacymigrationrun",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("run", "source_table", "source_id"), name="quality_legacy_source_unique"
                    )
                ]
            },
        ),
    ]
