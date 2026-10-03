from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0026_alter_post_content_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedslideconfig",
            name="overflow_mode",
            field=models.CharField(
                choices=[
                    ("scroll", "Scroll top to bottom"),
                    ("scale", "Scale down to fit"),
                    ("clip", "Clip overflow"),
                ],
                default="clip",
                max_length=10,
            ),
        ),
    ]
