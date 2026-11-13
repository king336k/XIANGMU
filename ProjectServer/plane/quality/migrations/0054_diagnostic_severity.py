from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("quality", "0053_verification_tasks")]

    operations = [
        migrations.AddField(
            model_name="defect", name="severity_origin", field=models.CharField(default="manual", max_length=16)
        ),
        migrations.AddField(
            model_name="defect", name="severity_reason", field=models.CharField(blank=True, max_length=2000)
        ),
        migrations.AddField(
            model_name="defect",
            name="severity_job",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="quality.diagnosticjob",
            ),
        ),
    ]
