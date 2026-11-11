# SPDX-License-Identifier: AGPL-3.0-only
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0040_legacy_migration_audit")]
    operations = [
        migrations.AddField(model_name="dataregression", name="request_snapshot", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="testexecution", name="reason_category", field=models.CharField(blank=True, max_length=24)),
        migrations.AddField(model_name="testexecution", name="next_action", field=models.TextField(blank=True)),
    ]
