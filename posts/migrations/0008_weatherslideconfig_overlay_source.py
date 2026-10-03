from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0007_calendarslideconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='weatherslideconfig',
            name='overlay_source',
            field=models.CharField(
                choices=[
                    ('rainviewer', 'RainViewer radar/clouds'),
                    ('nasa_gibs', 'NASA GIBS GOES-East satellite'),
                ],
                default='rainviewer',
                max_length=30,
            ),
        ),
    ]
