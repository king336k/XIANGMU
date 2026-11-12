from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils.dateparse import parse_datetime


def restore_projected_access(apps, schema_editor):
    """Rolling back the feature must also remove its projected management authority."""
    grants = apps.get_model("quality", "AdministratorAccessGrant")
    alias = schema_editor.connection.alias
    for grant in grants.objects.using(alias).all().iterator():
        model = apps.get_model("db", "WorkspaceMember" if grant.scope == "workspace" else "ProjectMember")
        prior = grant.previous_access
        values = (
            {"role": 5, "is_active": False}
            if prior is None
            else {
                "role": prior["role"],
                "is_active": prior["is_active"],
                "deleted_at": parse_datetime(prior["deleted_at"]) if prior["deleted_at"] else None,
            }
        )
        model.objects.using(alias).filter(pk=grant.membership_id, member_id=grant.user_id).update(**values)


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0046_solution_contributor_ids"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="AdministratorAccessGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "scope",
                    models.CharField(choices=[("workspace", "workspace"), ("project", "project")], max_length=10),
                ),
                ("target_id", models.UUIDField()),
                ("membership_id", models.UUIDField()),
                ("previous_access", models.JSONField(null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "scope", "target_id"), name="quality_admin_access_scope_unique"
                    )
                ]
            },
        ),
        migrations.RunPython(migrations.RunPython.noop, restore_projected_access),
    ]
