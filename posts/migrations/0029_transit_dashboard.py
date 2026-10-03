from django.db import migrations, models
import django.core.validators


ROUTES = [
    ("WS", "Westside Shuttle"),
    ("MS", "Main Street Shuttle"),
    ("DCL", "Downtown Center-Leroy Shuttle"),
    ("UDC", "University Downtown Center"),
    ("DS", "Downtown Southside Shuttle"),
    ("UC", "UClub Shuttle"),
    ("IU", "ITC-UClub Shuttle"),
    ("CS", "Campus Shuttle"),
    ("VS", "Vestal Shopping Shuttle"),
    ("OC", "Oakdale Commons Shuttle"),
    ("DE", "Downtown Express"),
    ("RIU", "Residential-ITC-UClub Shuttle"),
    ("ICS", "ITC Campus Shuttle"),
    ("IL", "Campus Shuttle Inner Loop"),
]


def add_routes(apps, schema_editor):
    Route = apps.get_model("posts", "TransitRoute")
    for order, (code, name) in enumerate(ROUTES, start=1):
        Route.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "color": "#005a43",
                "schedule_url": f"https://occtransport.org/routes/{code.lower()}.html",
                "sort_order": order,
                "is_active": True,
            },
        )


def remove_routes(apps, schema_editor):
    apps.get_model("posts", "TransitRoute").objects.filter(
        code__in=[code for code, _ in ROUTES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("posts", "0028_generatedslideconfig_scroll_speed")]

    operations = [
        migrations.CreateModel(
            name="TransitRoute",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("color", models.CharField(default="#005a43", max_length=7, validators=[django.core.validators.RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a six-digit hex color.")])),
                ("schedule_url", models.URLField(blank=True, max_length=500)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ("sort_order", "code")},
        ),
        migrations.CreateModel(
            name="TransitDashboardConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_visible", models.BooleanField(default=False)),
                ("duration_seconds", models.PositiveIntegerField(default=30, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(3600)])),
                ("selected_routes", models.ManyToManyField(blank=True, related_name="dashboard_configs", to="posts.transitroute")),
            ],
            options={"abstract": False},
        ),
        migrations.RunPython(add_routes, remove_routes),
    ]
