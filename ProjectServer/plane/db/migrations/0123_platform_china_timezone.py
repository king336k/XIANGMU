from django.db import migrations, models
import pytz


def unify_timezones(apps, schema_editor):
    for name, field in [("User", "user_timezone"), ("Workspace", "timezone"), ("Project", "timezone")]:
        apps.get_model("db", name).objects.using(schema_editor.connection.alias).exclude(
            **{field: "Asia/Shanghai"}
        ).update(**{field: "Asia/Shanghai"})


class Migration(migrations.Migration):
    dependencies = [("db", "0122_alter_draftissue_assignees_alter_issue_assignees_and_more")]
    operations = [
        migrations.AlterField(
            model_name=name,
            name=field,
            field=models.CharField(
                choices=tuple(zip(pytz.common_timezones, pytz.common_timezones)),
                default="Asia/Shanghai",
                max_length=255,
            ),
        )
        for name, field in [("user", "user_timezone"), ("workspace", "timezone"), ("project", "timezone")]
    ] + [migrations.RunPython(unify_timezones, migrations.RunPython.noop)]
