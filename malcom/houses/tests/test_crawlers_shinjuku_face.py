from django.test import TestCase

from houses.crawlers import ShinjukuFaceCrawler
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

SCHEDULE_HTML = """\
<!DOCTYPE html>
<html lang="ja">
<head><title>6月 | 2026 | Shinjuku FACE</title></head>
<body>
<span class="eventkijiyear">2026．</span>
<span class="eventkijimonth">06</span>
<a href="https://shinjuku-face.com/event/date/2026/07">next month</a>

<article class="post-100 events type-events status-publish">
<div class="eventlist eventmonthlist">
<div class="eventlist-info">
<div class="eventlist-single-date">
<div class="dayweek"><div class="day">01</div><div class="week">Mon</div></div>
<div class="eventtitle">
<div class="title_lineup"><a href="https://shinjuku-face.com/events/100">TestBand Alpha</a></div>
<div class="title_title"><a href="https://shinjuku-face.com/events/100">Summer Live 2026</a></div>
</div>
</div>
<div class="eventlist-detail">
<dl class="eventlist-detail">
<dt>OPEN／START</dt>
<dd>18:15 ／ 19:00</dd>
</dl>
</div>
</div>
</div>
</article>

<article class="post-101 events type-events status-publish">
<div class="eventlist eventmonthlist">
<div class="eventlist-info">
<div class="eventlist-single-date">
<div class="dayweek"><div class="day">15</div><div class="week">Tue</div></div>
<div class="eventtitle">
<div class="title_lineup"><a href="https://shinjuku-face.com/events/101">テストバンド</a></div>
<div class="title_title"><a href="https://shinjuku-face.com/events/101">秋のライブ</a></div>
</div>
</div>
<div class="eventlist-detail">
<dl class="eventlist-detail">
<dt>OPEN／START</dt>
<dd>17:30 ／ 18:00</dd>
</dl>
</div>
</div>
</div>
</article>
</body>
</html>
"""

NO_YEAR_MONTH_HTML = """\
<html><body>
<article>
<div class="day">01</div>
<div class="title_lineup"><a>BandX</a></div>
</article>
</body></html>
"""


class TestShinjukuFaceCrawler(TestCase):
    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="https://shinjuku-face.com/event/date/2026/06",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="ShinjukuFaceCrawler",
        )
        self.crawler = ShinjukuFaceCrawler(self.website)

    def test_extract_live_house_info(self):
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "Shinjuku FACE")

    def test_find_schedule_link_format(self):
        import datetime
        from unittest.mock import patch

        with patch("houses.crawlers.shinjuku_face.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 6, 1)
            url = self.crawler.find_schedule_link("")
        self.assertEqual(url, "https://shinjuku-face.com/event/date/2026/06")

    def test_find_schedule_link_zero_padded_month(self):
        import datetime
        from unittest.mock import patch

        with patch("houses.crawlers.shinjuku_face.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 3, 1)
            url = self.crawler.find_schedule_link("")
        self.assertEqual(url, "https://shinjuku-face.com/event/date/2026/03")

    def test_extract_schedules_parses_two_events(self):
        schedules = self.crawler.extract_performance_schedules(SCHEDULE_HTML)
        self.assertEqual(len(schedules), 2)

        june1 = schedules[0]
        self.assertEqual(june1["date"], "2026-06-01")
        self.assertEqual(june1["open_time"], "18:15")
        self.assertEqual(june1["start_time"], "19:00")
        self.assertIn("TestBand Alpha", june1["performers"])
        self.assertEqual(june1["performance_name"], "Summer Live 2026")

        june15 = schedules[1]
        self.assertEqual(june15["date"], "2026-06-15")
        self.assertEqual(june15["open_time"], "17:30")
        self.assertEqual(june15["start_time"], "18:00")
        self.assertIn("テストバンド", june15["performers"])
        self.assertEqual(june15["performance_name"], "秋のライブ")

    def test_extract_year_month_strips_punctuation(self):
        soup = self.crawler.create_soup(SCHEDULE_HTML)
        year, month = self.crawler._extract_year_month(soup)
        self.assertEqual(year, 2026)
        self.assertEqual(month, 6)

    def test_extract_schedules_no_year_month_returns_empty(self):
        schedules = self.crawler.extract_performance_schedules(NO_YEAR_MONTH_HTML)
        self.assertEqual(schedules, [])

    def test_find_next_month_link(self):
        url = self.crawler.find_next_month_link(SCHEDULE_HTML)
        self.assertEqual(url, "https://shinjuku-face.com/event/date/2026/07")
