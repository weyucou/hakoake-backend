from django.db import migrations


def set_cyclone_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=11).update(crawler_class="CycloneCrawler")


def reverse_cyclone_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=11, crawler_class="CycloneCrawler").update(
        crawler_class="LiveHouseWebsiteCrawler"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("houses", "0015_weeklyplaylist_instagram_story_id"),
    ]

    operations = [
        migrations.RunPython(set_cyclone_crawler_class, reverse_cyclone_crawler_class),
    ]
