from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("db", "0123_platform_china_timezone")]
    operations = [
        migrations.AddField(
            model_name="project", name="hidden_menu_items", field=models.JSONField(blank=True, default=list)
        )
    ]
