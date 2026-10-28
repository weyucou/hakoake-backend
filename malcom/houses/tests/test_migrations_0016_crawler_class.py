import importlib

from django.apps import apps
from django.test import TestCase

from houses.models import LiveHouseWebsite

# (migration module, forward function, house url, expected crawler_class)
MIGRATIONS = [
    (
        "0016_set_club_quattro_crawler_class",
        "set_club_quattro_crawler_class",
        "https://en.club-quattro.com/shibuya/",
        "ClubQuattroCrawler",
    ),
    (
        "0016_set_cyclone_crawler_class",
        "set_cyclone_crawler_class",
        "http://www.cyclone1997.com/home.html",
        "CycloneCrawler",
    ),
    (
        "0016_set_seventh_floor_crawler_class",
        "set_seventh_floor_crawler_class",
        "http://7th-floor.net/",
        "SeventhFloorCrawler",
    ),
    (
        "0016_set_shinjuku_face_crawler_class",
        "set_shinjuku_face_crawler_class",
        "https://shinjuku-face.com/",
        "ShinjukuFaceCrawler",
    ),
    ("0016_set_warp_crawler_class", "set_warp_crawler_class", "http://warp.rinky.info/", "WarpCrawler"),
]

# Houses that held the hard-coded ids 7, 8, 12, 13 on the cron host DB (#146)
UNRELATED = [
    ("https://club-malcolm.com/", "MalcolmCrawler"),
    ("https://www.unit-tokyo.com/", "LiveHouseWebsiteCrawler"),
    ("https://www.loft-prj.co.jp/schedule/loft", "LoftProjectShelterCrawler"),
    ("https://www.fever-popo.com/", "FeverPopoCrawler"),
    ("https://cyclone1997.com/", ""),
]


class CrawlerClassMigrationsTestCase(TestCase):
    def setUp(self):
        for _, _, url, _ in MIGRATIONS:
            LiveHouseWebsite.objects.create(url=url, crawler_class="LiveHouseWebsiteCrawler")
        for url, crawler_class in UNRELATED:
            LiveHouseWebsite.objects.create(url=url, crawler_class=crawler_class)

    def test_forward_selects_house_by_url(self):
        for module_name, function_name, _, _ in MIGRATIONS:
            module = importlib.import_module(f"houses.migrations.{module_name}")
            getattr(module, function_name)(apps, None)

        for _, _, url, expected in MIGRATIONS:
            self.assertEqual(LiveHouseWebsite.objects.get(url=url).crawler_class, expected, url)
        for url, crawler_class in UNRELATED:
            self.assertEqual(LiveHouseWebsite.objects.get(url=url).crawler_class, crawler_class, url)

    def test_reverse_restores_default_crawler(self):
        for module_name, function_name, _, _ in MIGRATIONS:
            module = importlib.import_module(f"houses.migrations.{module_name}")
            getattr(module, function_name)(apps, None)
            getattr(module, function_name.replace("set_", "reverse_", 1))(apps, None)

        for _, _, url, _ in MIGRATIONS:
            self.assertEqual(LiveHouseWebsite.objects.get(url=url).crawler_class, "LiveHouseWebsiteCrawler", url)
