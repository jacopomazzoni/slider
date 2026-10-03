from django.db import migrations, models


PROVIDER_ROUTE_IDS = {
    "WS": [1, 2], "MS": [12, 13], "DCL": [3, 4], "UDC": [6, 16],
    "DS": [14, 15], "UC": [5], "IU": [7], "CS": [8], "VS": [9],
    "OC": [10], "DE": [11], "IL": [19], "RIU": [], "ICS": [],
}


def set_provider_ids(apps, schema_editor):
    Route = apps.get_model("posts", "TransitRoute")
    for code, route_ids in PROVIDER_ROUTE_IDS.items():
        Route.objects.filter(code=code).update(provider_route_ids=route_ids)


class Migration(migrations.Migration):
    dependencies = [("posts", "0032_transit_inner_loop_schedule_url")]

    operations = [
        migrations.AddField(
            model_name="transitroute",
            name="provider_route_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(set_provider_ids, migrations.RunPython.noop),
    ]
