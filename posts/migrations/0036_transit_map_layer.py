from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0035_transit_side_panel_settings")]

    operations = [
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="map_layer",
            field=models.CharField(default="OpenStreetMap.Mapnik", max_length=128),
        ),
    ]
