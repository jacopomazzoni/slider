from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posts", "0020_post_is_visible"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="google_slides_advance_seconds",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                validators=[MinValueValidator(1), MaxValueValidator(3600)],
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="google_slides_end_slide",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                validators=[MinValueValidator(1), MaxValueValidator(2000)],
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="google_slides_start_slide",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                validators=[MinValueValidator(1), MaxValueValidator(2000)],
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="google_slides_url",
            field=models.URLField(blank=True, max_length=2000, null=True),
        ),
    ]
