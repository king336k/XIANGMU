import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('quality','0059_remote_identity_feedback_binding'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[migrations.CreateModel(name='RemoteFileRequest',fields=[
        ('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),
        ('identity_key',models.CharField(max_length=64)),
        ('command',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='file_request',to='quality.remotecommand')),
        ('owner',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
    ])]
