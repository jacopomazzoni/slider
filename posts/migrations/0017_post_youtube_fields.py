from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0016_siteappearancesettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='youtube_end_seconds',
            field=models.PositiveIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(86400)]),
        ),
        migrations.AddField(
            model_name='post',
            name='youtube_start_seconds',
            field=models.PositiveIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(86400)]),
        ),
        migrations.AddField(
            model_name='post',
            name='youtube_url',
            field=models.URLField(blank=True, max_length=1000, null=True),
        ),
        migrations.AlterField(
            model_name='post',
            name='content_type',
            field=models.CharField(choices=[('image', 'Image/PDF Slide'), ('video', 'Video Slide'), ('custom', 'Rich Text'), ('html', 'Custom HTML'), ('youtube', 'YouTube Slide')], default='image', max_length=10),
        ),
    ]
