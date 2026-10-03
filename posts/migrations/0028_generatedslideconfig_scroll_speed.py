import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0027_generatedslideconfig_overflow_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedslideconfig",
            name="scroll_speed",
            field=models.PositiveIntegerField(
                default=80,
                validators=[
                    django.core.validators.MinValueValidator(10),
                    django.core.validators.MaxValueValidator(1000),
                ],
            ),
        ),
    ]
