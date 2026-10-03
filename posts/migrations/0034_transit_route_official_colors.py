from django.db import migrations


ROUTE_COLORS = {
    "WS": "#191970",
    "MS": "#6495ED",
    "DCL": "#D2042D",
    "UDC": "#FF7F50",
    "DS": "#708090",
    "UC": "#BF40BF",
    "IU": "#CF9FFF",
    "CS": "#228B22",
    "VS": "#E37383",
    "OC": "#EAD653",
    "DE": "#000000",
    "IL": "#228B22",
}


def set_official_colors(apps, schema_editor):
    Route = apps.get_model("posts", "TransitRoute")
    for code, color in ROUTE_COLORS.items():
        Route.objects.filter(code=code).update(color=color)


class Migration(migrations.Migration):
    dependencies = [("posts", "0033_transitroute_provider_route_ids")]

    operations = [migrations.RunPython(set_official_colors, migrations.RunPython.noop)]
