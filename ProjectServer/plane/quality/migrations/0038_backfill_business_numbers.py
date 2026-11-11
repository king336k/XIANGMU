from django.db import migrations

RESOURCES = {
    "quality.Defect": "D",
    "quality.TestCase": "C",
    "quality.TestPlan": "P",
    "quality.TestSuite": "S",
    "quality.TestExecution": "E",
    "quality.Solution": "SOL",
    "quality.Release": "REL",
    "quality.ProjectVersion": "V",
    "quality.ProblemPackage": "PKG",
    "quality.SavedReport": "REP",
    "quality.TestResource": "RES",
    "quality.FieldAgent": "AG",
    "knowledge.Article": "K",
}


def populate(apps, schema_editor):
    using = schema_editor.connection.alias
    Number = apps.get_model("quality", "BusinessNumber")
    for label, prefix in RESOURCES.items():
        Model = apps.get_model(label)
        counters, batch = {}, []
        for pk, project_id, workspace_id, identifier in (
            Model.objects.using(using)
            .order_by("project_id", "created_at", "id")
            .values_list("pk", "project_id", "project__workspace_id", "project__identifier")
            .iterator(chunk_size=1000)
        ):
            counters[project_id] = counters.get(project_id, 0) + 1
            batch.append(
                Number(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    resource=label.lower(),
                    object_id=pk,
                    number=counters[project_id],
                    code=f"{identifier}-{prefix}-{counters[project_id]}",
                )
            )
            if len(batch) == 1000:
                Number.objects.using(using).bulk_create(batch)
                batch = []
        if batch:
            Number.objects.using(using).bulk_create(batch)


class Migration(migrations.Migration):
    dependencies = [("quality", "0037_business_numbers"), ("knowledge", "0002_article_merged_into")]
    operations = [migrations.RunPython(populate, migrations.RunPython.noop)]
