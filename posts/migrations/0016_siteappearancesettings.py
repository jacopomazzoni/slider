from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0015_post_media_revision_post_media_variants_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteAppearanceSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('logo', models.FileField(blank=True, null=True, upload_to='branding/', validators=[FileExtensionValidator(['png', 'svg'])])),
                ('favicon', models.FileField(blank=True, null=True, upload_to='branding/', validators=[FileExtensionValidator(['png', 'svg', 'ico'])])),
                ('theme_color', models.CharField(default='#005A43', max_length=7, validators=[RegexValidator(message='Use a valid 6-digit hex color, for example #005A43.', regex='^#[0-9A-Fa-f]{6}$')])),
                ('asset_revision', models.PositiveIntegerField(default=0, editable=False)),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
