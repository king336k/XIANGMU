from django.db import migrations,models
class Migration(migrations.Migration):
    dependencies=[('quality','0060_remote_file_request')]
    operations=[migrations.AddField(model_name='remoteagentrun',name='mode',field=models.CharField(default='repair',max_length=16))]
