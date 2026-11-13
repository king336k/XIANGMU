from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("quality", "0049_remove_reporter_duty"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="defectcomment", name="content_html", field=models.TextField(blank=True)),
        migrations.AddField(
            model_name="defectcomment", name="request_id", field=models.UUIDField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="defectcomment", name="request_hash", field=models.CharField(blank=True, max_length=64)
        ),
        migrations.AddField(
            model_name="defectcomment",
            name="reply_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="replies",
                to="quality.defectcomment",
            ),
        ),
        migrations.AddConstraint(
            model_name="defectcomment",
            constraint=models.UniqueConstraint(
                fields=("defect", "created_by", "request_id"), name="quality_comment_request_unique"
            ),
        ),
        migrations.CreateModel(
            name="CommentAttachment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("name", models.CharField(max_length=255)),
                ("size", models.PositiveBigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("storage_key", models.CharField(max_length=64)),
                ("content_type", models.CharField(max_length=100)),
                (
                    "comment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attachments",
                        to="quality.defectcomment",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "defect",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="comment_files", to="quality.defect"
                    ),
                ),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="db.project")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
