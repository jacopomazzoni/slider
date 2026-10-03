from django.core.validators import RegexValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0021_post_google_slides_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="BreakingNewsTickerConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "mode",
                    models.CharField(
                        choices=[("off", "Off"), ("on", "On")],
                        default="off",
                        max_length=10,
                    ),
                ),
                ("include_dateline_titles", models.BooleanField(default=False)),
                ("include_weather_alerts", models.BooleanField(default=False)),
                ("include_custom_text", models.BooleanField(default=False)),
                ("custom_text", models.CharField(blank=True, max_length=500)),
                (
                    "text_color",
                    models.CharField(
                        default="#FFFFFF",
                        max_length=7,
                        validators=[
                            RegexValidator(
                                message="Use a valid 6-digit hex color, for example #005A43.",
                                regex="^#[0-9A-Fa-f]{6}$",
                            )
                        ],
                    ),
                ),
                (
                    "background_color",
                    models.CharField(
                        default="#B42318",
                        max_length=7,
                        validators=[
                            RegexValidator(
                                message="Use a valid 6-digit hex color, for example #005A43.",
                                regex="^#[0-9A-Fa-f]{6}$",
                            )
                        ],
                    ),
                ),
            ],
        ),
    ]
