# Generated manually to add configurable weather dashboard slides.

import django.core.validators
from django.db import migrations, models


def create_default_weather_config(apps, schema_editor):
    WeatherSlideConfig = apps.get_model('posts', 'WeatherSlideConfig')
    WeatherSlideConfig.objects.get_or_create(
        pk=1,
        defaults={
            'is_visible': True,
            'map_layer': 'osm_hot',
            'duration_seconds': 24,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0005_generatedslideconfig'),
    ]

    operations = [
        migrations.CreateModel(
            name='WeatherSlideConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_visible', models.BooleanField(default=True)),
                ('map_layer', models.CharField(
                    choices=[
                        ('osm_hot', 'OpenStreetMap Humanitarian'),
                        ('osm_standard', 'OpenStreetMap Standard'),
                        ('opentopomap', 'OpenTopoMap'),
                        ('cyclosm', 'CyclOSM'),
                    ],
                    default='osm_hot',
                    max_length=30,
                )),
                ('duration_seconds', models.PositiveIntegerField(
                    default=24,
                    validators=[
                        django.core.validators.MinValueValidator(1),
                        django.core.validators.MaxValueValidator(3600),
                    ],
                )),
            ],
        ),
        migrations.RunPython(create_default_weather_config, migrations.RunPython.noop),
    ]
