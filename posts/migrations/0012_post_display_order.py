from django.db import migrations, models


def assign_post_display_order(apps, schema_editor):
    Post = apps.get_model('posts', 'Post')
    for index, post in enumerate(Post.objects.order_by('id'), start=1):
        Post.objects.filter(pk=post.pk).update(display_order=index)


class Migration(migrations.Migration):

    dependencies = [
        ('posts', '0011_generatedslideconfig_transition_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='display_order',
            field=models.PositiveIntegerField(db_index=True, default=0),
        ),
        migrations.RunPython(assign_post_display_order, migrations.RunPython.noop),
    ]
