from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[('quality','0063_remote_auto_enrollment_target')]
    operations=[
        migrations.AddField(model_name='remoteagentrun',name='started_at',field=models.DateTimeField(null=True,blank=True)),
        migrations.AddField(model_name='remoteagentrun',name='completed_at',field=models.DateTimeField(null=True,blank=True)),
    ]
