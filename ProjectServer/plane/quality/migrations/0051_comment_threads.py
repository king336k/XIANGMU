from django.db import migrations, models
import django.db.models.deletion


def backfill_threads(apps, schema_editor):
    comments = apps.get_model("quality", "DefectComment")
    using = schema_editor.connection.alias
    queryset = comments.objects.using(using)
    # Cache only ancestry IDs, scoped by defect; no historical text or attachment payload is retained.
    resolved = {}
    current_scope = None
    # Only ancestry metadata is backfilled. Content, reply targets, ownership and public replies remain unchanged.
    for row in (
        queryset.filter(visibility="internal", reply_to__isnull=False)
        .order_by("defect_id", "created_at", "id")
        .only("id", "defect_id", "project_id", "reply_to_id")
        .iterator(chunk_size=500)
    ):
        if current_scope != (row.defect_id, row.project_id):
            resolved.clear()
            current_scope = (row.defect_id, row.project_id)
        seen = {row.id}
        path = [row.id]
        parent_id = row.reply_to_id
        root_id = None
        while parent_id is not None:
            if parent_id in seen:
                break
            if parent_id in resolved:
                root_id = resolved[parent_id]
                break
            seen.add(parent_id)
            parent = (
                queryset.filter(pk=parent_id)
                .values("id", "defect_id", "project_id", "visibility", "reply_to_id")
                .first()
            )
            if (
                not parent
                or parent["visibility"] != "internal"
                or parent["defect_id"] != row.defect_id
                or parent["project_id"] != row.project_id
            ):
                break
            if parent["reply_to_id"] is None:
                root_id = parent["id"]
                resolved[parent_id] = root_id
                break
            path.append(parent_id)
            parent_id = parent["reply_to_id"]
        resolved.update({node_id: root_id for node_id in path})
        queryset.filter(pk=row.id).update(thread_root_id=root_id)


def clear_threads(apps, schema_editor):
    apps.get_model("quality", "DefectComment").objects.using(schema_editor.connection.alias).update(thread_root=None)


class Migration(migrations.Migration):
    dependencies = [("quality", "0050_defect_discussion")]
    operations = [
        migrations.AddField(
            model_name="defectcomment",
            name="thread_root",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="thread_replies",
                to="quality.defectcomment",
            ),
        ),
        migrations.RunPython(backfill_threads, clear_threads),
    ]
