from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0034_transit_route_official_colors")]

    operations = [
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="show_incoming_buses",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="show_service_alerts",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="transitdashboardconfig",
            name="side_panel_order",
            field=models.CharField(
                choices=[
                    ("incoming_first", "Next incoming buses, then service alerts"),
                    ("alerts_first", "Service alerts, then next incoming buses"),
                ],
                default="incoming_first",
                max_length=20,
            ),
        ),
    ]
