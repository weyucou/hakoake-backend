from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('houses', '0014_weeklyplaylist_shorts_video_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='weeklyplaylist',
            name='instagram_story_id',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
