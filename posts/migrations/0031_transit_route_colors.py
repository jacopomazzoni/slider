from django.db import migrations


ROUTE_COLORS = {
    "WS": "#c83d4d",
    "MS": "#1769aa",
    "DCL": "#d58616",
    "UDC": "#7353a6",
    "DS": "#27856b",
    "UC": "#bd4e99",
    "IU": "#4169a1",
    "CS": "#348b38",
    "VS": "#c15c22",
    "OC": "#527e28",
    "DE": "#485c70",
    "RIU": "#007c91",
    "ICS": "#a04434",
    "IL": "#6d7430",
}


def set_colors(apps, schema_editor):
    Route = apps.get_model("posts", "TransitRoute")
    for code, color in ROUTE_COLORS.items():
        Route.objects.filter(code=code).update(color=color)


class Migration(migrations.Migration):
    dependencies = [("posts", "0030_emptydisplay_transit")]
    operations = [migrations.RunPython(set_colors, migrations.RunPython.noop)]
