from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0038_transit_initial_map_offsets")]

    operations = [
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="initial_delay_seconds",
            field=models.PositiveIntegerField(
                default=0,
                validators=[MinValueValidator(0), MaxValueValidator(3600)],
            ),
        ),
    ]
