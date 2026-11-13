from django.db import migrations
from django.db.models import Max
from plane.utils.uuid import convert_uuid_to_integer


def link_manual_tasks(apps, schema_editor):
    Verification = apps.get_model("quality", "DefectVerification")
    Plan = apps.get_model("quality", "TestPlan")
    Number = apps.get_model("quality", "BusinessNumber")
    for row in (
        Verification.objects.using(schema_editor.connection.alias)
        .filter(plan__isnull=True)
        .select_related("defect", "project")
        .iterator()
    ):
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)", [convert_uuid_to_integer(f"{row.project_id}:quality.testplan")]
            )
        status = {
            "review": "review",
            "accepted": "completed",
            "testing": "running" if row.defect.status == "resolved" else "pending",
        }.get(row.status, "cancelled")
        plan = Plan.objects.using(schema_editor.connection.alias).create(
            project_id=row.project_id,
            created_by_id=row.created_by_id,
            name=f"{row.defect.title} · 人工验证 · 第{row.round_no}轮"[:255],
            build=row.fixed_build,
            environment=row.environment,
            round_no=row.round_no,
            status=status,
        )
        numbers = Number.objects.using(schema_editor.connection.alias)
        prefix = f"{row.project.identifier}-P-"
        last = (
            numbers.filter(project_id=row.project_id, resource="quality.testplan").aggregate(last=Max("number"))["last"]
            or 0
        )
        previous = (
            numbers.filter(workspace_id=row.project.workspace_id, code__startswith=prefix).aggregate(
                last=Max("number")
            )["last"]
            or 0
        )
        number = max(last, previous) + 1
        numbers.create(
            project_id=row.project_id,
            workspace_id=row.project.workspace_id,
            resource="quality.testplan",
            object_id=plan.id,
            number=number,
            code=f"{prefix}{number}",
        )
        row.plan_id = plan.id
        row.save(using=schema_editor.connection.alias, update_fields=["plan"])


class Migration(migrations.Migration):
    dependencies = [("quality", "0052_module_owners")]
    operations = [migrations.RunPython(link_manual_tasks, migrations.RunPython.noop)]
