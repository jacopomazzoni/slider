# Generated manually to add configurable public Google Calendar slides.

import django.core.validators
from django.db import migrations, models


def create_default_calendar_config(apps, schema_editor):
    CalendarSlideConfig = apps.get_model('posts', 'CalendarSlideConfig')
    CalendarSlideConfig.objects.get_or_create(
        pk=1,
        defaults={
            'is_visible': False,
            'public_url': '',
            'duration_seconds': 30,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0006_weatherslideconfig'),
    ]

    operations = [
        migrations.CreateModel(
            name='CalendarSlideConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_visible', models.BooleanField(default=False)),
                ('public_url', models.URLField(blank=True, max_length=2000)),
                ('duration_seconds', models.PositiveIntegerField(
                    default=30,
                    validators=[
                        django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(3600),
                    ],
                )),
            ],
        ),
        migrations.RunPython(create_default_calendar_config, migrations.RunPython.noop),
    ]
