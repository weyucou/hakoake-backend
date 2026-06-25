from django.test import TestCase

from houses.crawlers import SeventhFloorCrawler
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

SCHEDULE_HTML = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<title>渋谷 7thFLOOR schedule</title>
<link rel="canonical" href="http://7th-floor.net/event/?ym=2026-6"/>
</head>
<body>
<div class="eventList 2026-6">
<a href="http://7th-floor.net/event/test-event-1/">
<div class="headerWrap">
<div class="dateWrap">
<span class="date">06.07</span>
<span class="week">(日)</span>
</div>
</div>
<div class="infoWrap">
<h2><span class="evTit">Summer Acoustic Night</span></h2>
<ul class="artists">
<li>テストアーティスト1 / テストアーティスト2</li>
</ul>
</div>
</a>
</div>
<div class="eventList 2026-6">
<a href="http://7th-floor.net/event/test-event-2/">
<div class="headerWrap">
<div class="dateWrap">
<span class="date">06.20</span>
<span class="week">(土)</span>
</div>
</div>
<div class="infoWrap">
<h2><span class="evTit">Jazz Session Vol.5</span></h2>
<ul class="artists">
<li>BandX</li>
</ul>
</div>
</a>
</div>
<div class="eventList 2026-5">
<a href="http://7th-floor.net/event/may-event/">
<div class="headerWrap">
<div class="dateWrap">
<span class="date">05.10</span>
</div>
</div>
<div class="infoWrap">
<h2><span class="evTit">May Event</span></h2>
<ul class="artists"><li>OldBand</li></ul>
</div>
</a>
</div>
</body>
</html>
"""

NO_CANONICAL_HTML = """\
<html><body>
<div class="eventList 2026-7">
<span class="date">07.01</span>
<ul class="artists"><li>BandA</li></ul>
</div>
</body></html>
"""


class TestSeventhFloorCrawler(TestCase):
    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="http://7th-floor.net/event/",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="SeventhFloorCrawler",
        )
        self.crawler = SeventhFloorCrawler(self.website)

    def test_extract_live_house_info(self):
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "7th Floor")

    def test_find_schedule_link_format(self):
        import datetime
        from unittest.mock import patch

        with patch("houses.crawlers.seventh_floor.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 6, 1)
            url = self.crawler.find_schedule_link("")
        self.assertEqual(url, "http://7th-floor.net/event/?ym=2026-6")

    def test_extract_schedules_filters_by_target_month(self):
        schedules = self.crawler.extract_performance_schedules(SCHEDULE_HTML)
        self.assertEqual(len(schedules), 2)

        june7 = schedules[0]
        self.assertEqual(june7["date"], "2026-06-07")
        self.assertIn("テストアーティスト1 / テストアーティスト2", june7["performers"])
        self.assertEqual(june7["performance_name"], "Summer Acoustic Night")

        june20 = schedules[1]
        self.assertEqual(june20["date"], "2026-06-20")
        self.assertIn("BandX", june20["performers"])

    def test_may_events_excluded(self):
        schedules = self.crawler.extract_performance_schedules(SCHEDULE_HTML)
        dates = [s["date"] for s in schedules]
        self.assertNotIn("2026-05-10", dates)

    def test_extract_year_month_from_canonical_link(self):
        soup = self.crawler.create_soup(SCHEDULE_HTML)
        year, month = self.crawler._extract_target_year_month(soup)
        self.assertEqual(year, 2026)
        self.assertEqual(month, 6)

    def test_extract_year_month_falls_back_to_today_when_no_canonical(self):
        import datetime
        from unittest.mock import patch

        with patch("houses.crawlers.seventh_floor.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 7, 1)
            soup = self.crawler.create_soup(NO_CANONICAL_HTML)
            year, month = self.crawler._extract_target_year_month(soup)
        self.assertEqual(year, 2026)
        self.assertEqual(month, 7)
