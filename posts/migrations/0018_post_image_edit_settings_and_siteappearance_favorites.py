from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0017_post_youtube_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='image_edit_settings',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='siteappearancesettings',
            name='favorite_theme_colors',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
