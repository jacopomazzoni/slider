# Generated manually to add configurable slide durations.

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0003_add_video_media_support'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='duration_seconds',
            field=models.PositiveIntegerField(
                default=8,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(3600),
                ],
            ),
        ),
    ]
