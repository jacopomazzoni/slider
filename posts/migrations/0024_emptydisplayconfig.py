from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0023_breakingnewstickerconfig_typography"),
    ]

    operations = [
        migrations.CreateModel(
            name="EmptyDisplayConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(
                    choices=[
                        ("auto", "Automatic"),
                        ("message", "No Content Message"),
                        ("blank", "Blank Screen"),
                        ("dateline", "Dateline Announcements"),
                        ("weather", "Weather Dashboard"),
                        ("calendar", "Google Calendar"),
                    ],
                    default="auto",
                    max_length=20,
                )),
            ],
        ),
    ]
