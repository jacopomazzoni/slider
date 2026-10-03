from django.core import validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0022_breakingnewstickerconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="breakingnewstickerconfig",
            name="font_family",
            field=models.CharField(
                choices=[
                    ("system", "System Sans"),
                    ("arial", "Arial"),
                    ("verdana", "Verdana"),
                    ("trebuchet", "Trebuchet MS"),
                    ("georgia", "Georgia"),
                    ("times", "Times New Roman"),
                    ("courier", "Courier New"),
                ],
                default="system",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="breakingnewstickerconfig",
            name="font_size",
            field=models.PositiveIntegerField(
                default=20,
                validators=[validators.MinValueValidator(12), validators.MaxValueValidator(48)],
            ),
        ),
        migrations.AddField(
            model_name="breakingnewstickerconfig",
            name="scroll_speed",
            field=models.PositiveIntegerField(
                default=110,
                validators=[validators.MinValueValidator(20), validators.MaxValueValidator(400)],
            ),
        ),
    ]
