from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("quality", "0062_remote_uploaded_file")]
    operations = [
        migrations.AddField(model_name="remoteworkstation", name="enrollment_claim_hash",field=models.CharField(max_length=64,blank=True)),
        migrations.AddField(model_name="remoteworkstation", name="machine_fingerprint",field=models.CharField(max_length=64,blank=True)),
        migrations.AddField(model_name="remoteterminal", name="target",field=models.CharField(max_length=16,default="operator")),
        migrations.AddField(model_name="remoteterminal", name="target_identity",field=models.JSONField(default=dict)),
        migrations.AddField(model_name="remoteterminal", name="target_revision",field=models.CharField(max_length=64,blank=True)),
    ]
