from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0036_transit_map_layer")]

    operations = [
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="zoom_offset",
            field=models.SmallIntegerField(
                default=0,
                validators=[MinValueValidator(-5), MaxValueValidator(5)],
            ),
        ),
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="x_offset_meters",
            field=models.SmallIntegerField(
                default=0,
                validators=[MinValueValidator(-5000), MaxValueValidator(5000)],
            ),
        ),
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="y_offset_meters",
            field=models.SmallIntegerField(
                default=0,
                validators=[MinValueValidator(-5000), MaxValueValidator(5000)],
            ),
        ),
    ]
