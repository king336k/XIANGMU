import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("quality", "0058_remote_terminal_error"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="remoteagentrun", name="identity_key", field=models.CharField(blank=True, max_length=64)),
        migrations.CreateModel(
            name="RemoteFeedbackBinding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("defect", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="remote_bindings", to="quality.defect")),
                ("workstation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feedback_bindings", to="quality.remoteworkstation")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("workstation", "defect"), name="remote_feedback_binding_unique")]},
        ),
    ]
