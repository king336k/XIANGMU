from django.db import migrations, models


def assign_numbers(apps, schema_editor):
    Requirement = apps.get_model("quality", "Requirement")
    counters = {}
    for row in Requirement.objects.order_by("project_id", "created_at", "issue__sequence_id", "id").iterator():
        counters[row.project_id] = counters.get(row.project_id, 0) + 1
        Requirement.objects.filter(pk=row.pk).update(number=counters[row.project_id])


class Migration(migrations.Migration):
    dependencies = [("quality", "0030_reportdelivery_target_snapshot")]
    operations = [
        migrations.AddField(
            model_name="requirement", name="number", field=models.PositiveIntegerField(editable=False, null=True)
        ),
        migrations.RunPython(assign_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="requirement", name="number", field=models.PositiveIntegerField(editable=False)
        ),
        migrations.AddConstraint(
            model_name="requirement",
            constraint=models.UniqueConstraint(fields=("project", "number"), name="quality_requirement_number_unique"),
        ),
    ]
