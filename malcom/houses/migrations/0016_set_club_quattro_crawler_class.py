from django.db import migrations


def set_club_quattro_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(url="https://en.club-quattro.com/shibuya/").update(
        crawler_class="ClubQuattroCrawler"
    )


def reverse_club_quattro_crawler_class(apps, schema_editor):
    LiveHouseWebsite = apps.get_model("houses", "LiveHouseWebsite")
    LiveHouseWebsite.objects.filter(
        url="https://en.club-quattro.com/shibuya/", crawler_class="ClubQuattroCrawler"
    ).update(crawler_class="LiveHouseWebsiteCrawler")


class Migration(migrations.Migration):
    dependencies = [
        ("houses", "0015_weeklyplaylist_instagram_story_id"),
    ]

    operations = [
        migrations.RunPython(set_club_quattro_crawler_class, reverse_club_quattro_crawler_class),
    ]
