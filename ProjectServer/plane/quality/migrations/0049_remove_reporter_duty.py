"""Remove the obsolete duty only; authored defects, users and audit records remain."""

from django.db import migrations


def remove_reporter(apps, schema_editor):
    alias = schema_editor.connection.alias
    duties = apps.get_model("quality", "BusinessRole")
    for row in duties.objects.using(alias).all().iterator():
        wanted = [role for role in [row.role, *(row.additional_roles or [])] if role != "REPORTER"]
        if not wanted:
            row.delete(using=alias)
        elif wanted != [row.role, *(row.additional_roles or [])]:
            row.role, row.additional_roles = wanted[0], wanted[1:]
            row.save(using=alias, update_fields=["role", "additional_roles"])
    members = apps.get_model("db", "WorkspaceMember")
    for row in members.objects.using(alias).filter(business_roles__contains=["REPORTER"]).iterator():
        row.business_roles = [role for role in row.business_roles if role != "REPORTER"]
        row.save(using=alias, update_fields=["business_roles"])


class Migration(migrations.Migration):
    dependencies = [("quality", "0048_defect_verification"), ("db", "0126_workspacemember_has_workspace_access")]
    operations = [migrations.RunPython(remove_reporter, migrations.RunPython.noop)]
