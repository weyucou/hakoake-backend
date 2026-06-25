from django.test import TestCase

from houses.crawlers import ClubQuattroCrawler
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

SCHEDULE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><title>Schedule | Shibuya Club Quattro</title></head>
<body>
<span class="year">2026</span>
<span class="month">06</span>
<a href="https://en.club-quattro.com/shibuya/schedule/?ym=202607">next</a>
<div class="event-box">
  <a href="https://en.club-quattro.com/shibuya/schedule/detail/?cd=018366">
    <div class="date-wrap">
      <div class="date">
        <p class="day">01</p>
        <p class="week">MON.</p>
      </div>
    </div>
    <div class="cmn-event-info">
      <p class="txt-01"><span class="hv-elm">SHE'S</span></p>
      <p class="txt-02">SHE'S 15th Anniversary</p>
      <dl class="detail-list">
        <dt>Opening/Starting</dt>
        <dd>18:00 / 18:45</dd>
        <dd>Advance sale ¥5,500</dd>
      </dl>
    </div>
  </a>
</div>
<div class="event-box">
  <a href="https://en.club-quattro.com/shibuya/schedule/detail/?cd=018400">
    <div class="date-wrap">
      <div class="date">
        <p class="day">15</p>
        <p class="week">MON.</p>
      </div>
    </div>
    <div class="cmn-event-info">
      <p class="txt-01"><span class="hv-elm">テストバンド</span></p>
      <p class="txt-02">Summer Tour 2026</p>
      <dl class="detail-list">
        <dt>Opening/Starting</dt>
        <dd>17:30 / 18:00</dd>
      </dl>
    </div>
  </a>
</div>
</body>
</html>
"""

NO_YEAR_MONTH_HTML = """\
<html><body>
<div class="event-box">
  <p class="day">01</p>
</div>
</body></html>
"""


class TestClubQuattroCrawler(TestCase):
    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="https://en.club-quattro.com/shibuya/schedule/",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="ClubQuattroCrawler",
        )
        self.crawler = ClubQuattroCrawler(self.website)

    def test_extract_live_house_info(self):
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "CLUB QUATTRO")
        self.assertEqual(info["name_romaji"], "CLUB QUATTRO")

    def test_find_schedule_link_format(self):
        import datetime
        from unittest.mock import patch

        with patch("houses.crawlers.club_quattro.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 6, 1)
            url = self.crawler.find_schedule_link("")
        self.assertEqual(url, "https://en.club-quattro.com/shibuya/schedule/?ym=202606")

    def test_extract_schedules_parses_two_events(self):
        schedules = self.crawler.extract_performance_schedules(SCHEDULE_HTML)
        self.assertEqual(len(schedules), 2)

        june1 = schedules[0]
        self.assertEqual(june1["date"], "2026-06-01")
        self.assertEqual(june1["open_time"], "18:00")
        self.assertEqual(june1["start_time"], "18:45")
        self.assertIn("SHE'S", june1["performers"])
        self.assertEqual(june1["performance_name"], "SHE'S 15th Anniversary")

        june15 = schedules[1]
        self.assertEqual(june15["date"], "2026-06-15")
        self.assertEqual(june15["open_time"], "17:30")
        self.assertEqual(june15["start_time"], "18:00")
        self.assertIn("テストバンド", june15["performers"])

    def test_extract_schedules_no_year_month_returns_empty(self):
        schedules = self.crawler.extract_performance_schedules(NO_YEAR_MONTH_HTML)
        self.assertEqual(schedules, [])

    def test_find_next_month_link(self):
        url = self.crawler.find_next_month_link(SCHEDULE_HTML)
        self.assertEqual(url, "https://en.club-quattro.com/shibuya/schedule/?ym=202607")

    def test_find_next_month_link_year_rollover(self):
        html = """\
        <html><body>
        <span class="year">2026</span>
        <span class="month">12</span>
        <a href="https://en.club-quattro.com/shibuya/schedule/?ym=202701">jan</a>
        </body></html>
        """
        url = self.crawler.find_next_month_link(html)
        self.assertEqual(url, "https://en.club-quattro.com/shibuya/schedule/?ym=202701")
