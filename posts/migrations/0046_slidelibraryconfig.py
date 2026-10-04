from django.db import migrations, models
import posts.models


class Migration(migrations.Migration):
    dependencies = [('posts', '0045_screen_power_health')]
    operations = [migrations.CreateModel(
        name='SlideLibraryConfig',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('section_order', models.JSONField(default=posts.models.default_library_sections)),
        ],
    )]
