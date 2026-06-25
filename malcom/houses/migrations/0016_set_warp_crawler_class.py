from django.db import migrations


def set_warp_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=12).update(
        crawler_class="WarpCrawler",
        schedule_url="http://warp.rinky.info/",
    )


def reverse_warp_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(id=12, crawler_class="WarpCrawler").update(
        crawler_class="LiveHouseWebsiteCrawler",
        schedule_url="http://warp.rinky.info/schedules",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("houses", "0015_weeklyplaylist_instagram_story_id"),
    ]

    operations = [
        migrations.RunPython(set_warp_crawler_class, reverse_warp_crawler_class),
    ]
