from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posts", "0029_transit_dashboard")]

    operations = [
        migrations.AlterField(
            model_name="emptydisplayconfig",
            name="mode",
            field=models.CharField(
                choices=[
                    ("auto", "Automatic"),
                    ("message", "No Content Message"),
                    ("blank", "Blank Screen"),
                    ("dateline", "Dateline Announcements"),
                    ("weather", "Weather Dashboard"),
                    ("calendar", "Google Calendar"),
                    ("transit", "Campus Transit Dashboard"),
                ],
                default="auto",
                max_length=20,
            ),
        ),
    ]
