from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0044_external_release_snapshot")]

    operations = [
        migrations.AddField(
            model_name="defect",
            name="verification_scope",
            field=models.CharField(default="auto", max_length=16),
        ),
    ]
