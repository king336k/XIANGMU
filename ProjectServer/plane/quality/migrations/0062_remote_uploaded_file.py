import uuid
from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('quality','0061_remote_run_mode'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[migrations.CreateModel(name='RemoteUploadedFile',fields=[
        ('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),
        ('target',models.CharField(max_length=16)),('path',models.CharField(max_length=2000)),('filename',models.CharField(max_length=255)),
        ('sha256',models.CharField(max_length=64)),('size',models.PositiveBigIntegerField()),('ticket_hash',models.CharField(blank=True,max_length=64)),('identity_key',models.CharField(max_length=64)),
        ('status',models.CharField(default='uploading',max_length=16)),('created_at',models.DateTimeField(auto_now_add=True)),('expires_at',models.DateTimeField()),
        ('workstation',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to='quality.remoteworkstation')),
        ('owner',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
        ('defect',models.ForeignKey(null=True,on_delete=django.db.models.deletion.PROTECT,to='quality.defect'))])]
