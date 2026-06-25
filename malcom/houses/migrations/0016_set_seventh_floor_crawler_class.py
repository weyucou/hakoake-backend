from django.db import migrations


def set_seventh_floor_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=8).update(
        crawler_class="SeventhFloorCrawler",
        schedule_url="http://7th-floor.net/event/",
    )


def reverse_seventh_floor_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=8, crawler_class="SeventhFloorCrawler").update(
        crawler_class="LiveHouseWebsiteCrawler",
        schedule_url="http://7th-floor.net/schedules/",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("houses", "0015_weeklyplaylist_instagram_story_id"),
    ]

    operations = [
        migrations.RunPython(set_seventh_floor_crawler_class, reverse_seventh_floor_crawler_class),
    ]
