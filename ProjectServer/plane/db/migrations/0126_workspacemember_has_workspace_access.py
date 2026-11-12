from django.db import migrations, models


def preserve_workspace_duties(apps, schema_editor):
    members = apps.get_model("db", "WorkspaceMember")
    members.objects.using(schema_editor.connection.alias).exclude(business_roles=[]).update(has_workspace_access=True)


class Migration(migrations.Migration):
    dependencies = [("db", "0125_workspacemember_business_roles")]
    operations = [
        migrations.AddField(
            model_name="workspacemember", name="has_workspace_access", field=models.BooleanField(default=False)
        ),
        migrations.RunPython(preserve_workspace_duties, migrations.RunPython.noop),
    ]
