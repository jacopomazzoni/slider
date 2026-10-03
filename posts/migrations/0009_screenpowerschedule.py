import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0008_weatherslideconfig_overlay_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScreenPowerSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('screen_on_time', models.TimeField(default=datetime.time(8, 0))),
                ('screen_off_time', models.TimeField(default=datetime.time(17, 0))),
                ('last_screen_on_run', models.DateTimeField(blank=True, editable=False, null=True)),
                ('last_screen_off_run', models.DateTimeField(blank=True, editable=False, null=True)),
            ],
            options={},
        ),
    ]
