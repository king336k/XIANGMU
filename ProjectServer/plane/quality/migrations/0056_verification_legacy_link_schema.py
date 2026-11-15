"""Repair deployments that applied 0055 before its legacy-link fields existed.

The migration state already includes the fields in 0055. Inspect the physical
schema so both an original 0055 installation and a fresh database can upgrade.
Existing rows remain valid because both source links are nullable.
"""

from django.db import migrations


def ensure_legacy_links(apps, schema_editor):
    targets = (
        ("DefectVerificationCase", "source_plan_item", "quality_verification_legacy_plan_item_unique"),
        ("DefectVerificationCaseExecution", "source_execution", "quality_verification_legacy_execution_unique"),
    )
    for model_name, field_name, constraint_name in targets:
        model = apps.get_model("quality", model_name)
        field = model._meta.get_field(field_name)
        table = model._meta.db_table
        with schema_editor.connection.cursor() as cursor:
            columns = {
                column.name
                for column in schema_editor.connection.introspection.get_table_description(cursor, table)
            }
        if field.column not in columns:
            schema_editor.add_field(model, field)
        with schema_editor.connection.cursor() as cursor:
            constraints = schema_editor.connection.introspection.get_constraints(cursor, table)
        if constraint_name not in constraints:
            constraint = next(item for item in model._meta.constraints if item.name == constraint_name)
            schema_editor.add_constraint(model, constraint)


class Migration(migrations.Migration):
    dependencies = [("quality", "0055_verification_round_cases")]

    operations = [migrations.RunPython(ensure_legacy_links, migrations.RunPython.noop)]
