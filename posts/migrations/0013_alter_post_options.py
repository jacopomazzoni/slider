from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0012_post_display_order'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='post',
            options={'ordering': ['display_order', 'id']},
        ),
    ]
