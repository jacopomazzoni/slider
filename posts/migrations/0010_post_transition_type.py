from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0009_screenpowerschedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='transition_type',
            field=models.CharField(
                choices=[
                    ('fade_gray', 'Fade to Gray'),
                    ('fade_black', 'Fade to Black'),
                    ('fade_white', 'Fade to White'),
                    ('crossfade', 'Crossfade'),
                ],
                default='crossfade',
                max_length=20,
            ),
        ),
    ]
