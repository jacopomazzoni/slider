# Generated manually to add video media support.

import django.core.validators
from django.db import migrations, models
import posts.models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0002_post_content_type_post_description_post_link_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='content_type',
            field=models.CharField(
                choices=[
                    ('image', 'Image/PDF Slide'),
                    ('video', 'Video Slide'),
                    ('custom', 'Custom Content'),
                ],
                default='image',
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name='post',
            name='cover',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='images/',
                validators=[
                    django.core.validators.FileExtensionValidator([
                        'png', 'jpg', 'jpeg', 'gif', 'webp',
                        'mp4', 'm4v', 'mov', 'webm', 'ogv',
                        'pdf',
                    ]),
                    posts.models.validate_file_mimetype,
                ],
            ),
        ),
    ]
