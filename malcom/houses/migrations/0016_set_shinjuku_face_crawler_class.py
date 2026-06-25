from django.db import migrations


def set_shinjuku_face_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=13).update(crawler_class="ShinjukuFaceCrawler")


def reverse_shinjuku_face_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=13, crawler_class="ShinjukuFaceCrawler").update(
        crawler_class="LiveHouseWebsiteCrawler"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("houses", "0015_weeklyplaylist_instagram_story_id"),
    ]

    operations = [
        migrations.RunPython(set_shinjuku_face_crawler_class, reverse_shinjuku_face_crawler_class),
    ]
