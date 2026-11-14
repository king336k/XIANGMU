# Generated for defect-scoped library snapshots and private supplemental cases.
import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("quality", "0054_diagnostic_severity")]

    operations = [
        migrations.CreateModel(
            name="DefectVerificationCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("source", models.CharField(choices=[("library", "library"), ("round", "round")], max_length=16)),
                ("title", models.CharField(max_length=255)),
                ("snapshot", models.JSONField(default=dict)),
                ("position", models.PositiveIntegerField(default=0)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="db.user")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="db.project")),
                ("source_case", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="quality.testcase")),
                ("source_plan_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="quality.planitem")),
                ("source_revision", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="quality.caserevision")),
                ("verification", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="case_items", to="quality.defectverification")),
            ],
            options={"ordering": ["position", "created_at", "id"]},
        ),
        migrations.CreateModel(
            name="DefectVerificationCaseExecution",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("request_id", models.UUIDField()),
                ("request_hash", models.CharField(max_length=64)),
                ("result", models.CharField(max_length=16)),
                ("source_execution", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="quality.testexecution")),
                ("actual_result", models.TextField(blank=True)),
                ("evidence", models.TextField(blank=True)),
                ("step_results", models.JSONField(default=list)),
                ("reason_category", models.CharField(blank=True, max_length=24)),
                ("next_action", models.TextField(blank=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="db.user")),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="executions", to="quality.defectverificationcase")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="db.project")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="defectverificationcase",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(source="library", source_case__isnull=False, source_revision__isnull=False)
                    | models.Q(source="round", source_case__isnull=True, source_revision__isnull=True)
                ),
                name="quality_verification_case_source_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="defectverificationcase",
            constraint=models.UniqueConstraint(
                condition=models.Q(source_case__isnull=False),
                fields=("verification", "source_case"),
                name="quality_verification_library_case_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="defectverificationcase",
            constraint=models.UniqueConstraint(
                condition=models.Q(source_plan_item__isnull=False),
                fields=("source_plan_item",),
                name="quality_verification_legacy_plan_item_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="defectverificationcaseexecution",
            constraint=models.UniqueConstraint(fields=("item", "request_id"), name="quality_verification_case_execution_request_unique"),
        ),
        migrations.AddConstraint(
            model_name="defectverificationcaseexecution",
            constraint=models.UniqueConstraint(
                condition=models.Q(source_execution__isnull=False),
                fields=("source_execution",),
                name="quality_verification_legacy_execution_unique",
            ),
        ),
    ]
