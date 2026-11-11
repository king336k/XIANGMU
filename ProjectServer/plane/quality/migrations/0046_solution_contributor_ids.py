from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0045_defect_verification_scope")]

    operations = [
        migrations.AddField(
            model_name="solution", name="contributor_ids", field=models.JSONField(default=list, null=True)
        ),
    ]
