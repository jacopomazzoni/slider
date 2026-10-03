# Generated manually to add configurable scraper-generated slides.

import django.core.validators
from django.db import migrations, models


def create_default_dateline_config(apps, schema_editor):
    GeneratedSlideConfig = apps.get_model('posts', 'GeneratedSlideConfig')
    GeneratedSlideConfig.objects.get_or_create(
        scraper_name='dateline',
        defaults={
            'is_visible': True,
            'generated_slide_count': 3,
            'duration_seconds': 8,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0004_post_duration_seconds'),
    ]

    operations = [
        migrations.CreateModel(
            name='GeneratedSlideConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scraper_name', models.CharField(
                    choices=[('dateline', 'Dateline Announcements')],
                    default='dateline',
                    max_length=30,
                    unique=True,
                )),
                ('is_visible', models.BooleanField(default=True)),
                ('generated_slide_count', models.PositiveIntegerField(
                    default=3,
                    validators=[
                        django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(20),
                    ],
                )),
                ('duration_seconds', models.PositiveIntegerField(
                    default=8,
                    validators=[
                        django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(3600),
                    ],
                )),
            ],
        ),
        migrations.RunPython(create_default_dateline_config, migrations.RunPython.noop),
    ]
