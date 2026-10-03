from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('posts', '0044_activity_log')]
    operations = [
        migrations.AddField('screenpowerschedule', 'is_enabled', models.BooleanField(default=True)),
        migrations.AddField('screenpowerschedule', 'last_scheduler_check', models.DateTimeField(null=True, blank=True, editable=False)),
        migrations.AddField('screenpowerschedule', 'last_attempt_at', models.DateTimeField(null=True, blank=True, editable=False)),
        migrations.AddField('screenpowerschedule', 'last_applied_slot', models.CharField(max_length=40, blank=True, editable=False)),
        migrations.AddField('screenpowerschedule', 'last_error', models.TextField(blank=True, editable=False)),
    ]
