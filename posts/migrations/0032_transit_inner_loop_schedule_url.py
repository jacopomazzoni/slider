from django.db import migrations


def use_campus_shuttle_schedule(apps, schema_editor):
    apps.get_model("posts", "TransitRoute").objects.filter(code="IL").update(
        schedule_url="https://occtransport.org/routes/cs.html"
    )


class Migration(migrations.Migration):
    dependencies = [("posts", "0031_transit_route_colors")]
    operations = [migrations.RunPython(use_campus_shuttle_schedule, migrations.RunPython.noop)]
