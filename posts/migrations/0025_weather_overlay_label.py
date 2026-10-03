from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0024_emptydisplayconfig"),
    ]

    operations = [
        migrations.AlterField(
            model_name="weatherslideconfig",
            name="overlay_source",
            field=models.CharField(
                choices=[
                    ("rainviewer", "RainViewer radar (precipitation only)"),
                    ("nasa_gibs", "NASA GIBS GOES-East satellite"),
                ],
                default="rainviewer",
                max_length=30,
            ),
        ),
    ]
