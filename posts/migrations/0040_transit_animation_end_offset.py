from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0039_transit_initial_delay")]

    operations = [
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="animation_end_offset_seconds",
            field=models.PositiveIntegerField(
                default=1,
                validators=[MinValueValidator(0), MaxValueValidator(3600)],
            ),
        ),
    ]
