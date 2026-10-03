from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


def clamp_animation_timing(apps, schema_editor):
    config_model = apps.get_model("posts", "TransitDashboardConfig")
    for config in config_model.objects.all().iterator():
        duration = max(1, config.duration_seconds or 1)
        delay = min(20, max(0, config.initial_delay_seconds or 0))
        end_offset = min(20, max(0, config.animation_end_offset_seconds or 0))
        if delay + end_offset >= duration:
            end_offset = min(end_offset, max(0, duration - delay - 1))
            if delay + end_offset >= duration:
                delay = max(0, duration - 1)
                end_offset = 0
        config.initial_delay_seconds = delay
        config.animation_end_offset_seconds = end_offset
        config.save(update_fields=["initial_delay_seconds", "animation_end_offset_seconds"])


class Migration(migrations.Migration):
    dependencies = [("posts", "0040_transit_animation_end_offset")]

    operations = [
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="animation_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="animation_easing",
            field=models.CharField(
                choices=[("gentle", "Gentle"), ("smooth", "Smooth"), ("brisk", "Direct")],
                default="smooth",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="transitdashboardconfig",
            name="initial_delay_seconds",
            field=models.PositiveIntegerField(
                default=0,
                validators=[MinValueValidator(0), MaxValueValidator(20)],
            ),
        ),
        migrations.AlterField(
            model_name="transitdashboardconfig",
            name="animation_end_offset_seconds",
            field=models.PositiveIntegerField(
                default=1,
                validators=[MinValueValidator(0), MaxValueValidator(20)],
            ),
        ),
        migrations.RunPython(clamp_animation_timing, migrations.RunPython.noop),
    ]
