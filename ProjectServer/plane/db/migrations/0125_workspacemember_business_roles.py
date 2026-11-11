from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("db", "0124_project_hidden_menu_items")]
    operations = [
        migrations.AddField(
            model_name="workspacemember", name="business_roles", field=models.JSONField(blank=True, default=list)
        )
    ]
