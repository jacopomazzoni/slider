from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0025_weather_overlay_label"),
    ]

    operations = [
        migrations.AlterField(
            model_name="post",
            name="content_type",
            field=models.CharField(
                choices=[
                    ("image", "Image/PDF Slide"),
                    ("video", "Video Slide"),
                    ("custom", "Rich Text"),
                    ("html", "Custom HTML"),
                    ("youtube", "YouTube Slide"),
                    ("gslides", "Google Slides"),
                ],
                default="image",
                max_length=10,
            ),
        ),
    ]
