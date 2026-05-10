from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from houses.crawlers import ShibuyaONestCrawler
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

DETAIL_HTML_FULL = """\
<html lang="ja">
<body>
<div id="content" class="l-content p-schedule-detail">
  <div class="p-schedule-detail__row">
    <div class="p-schedule-detail__image">
      <div class="p-schedule-detail__image-item">
        <img src="https://example.com/flyer.jpg"
             class="attachment-large size-large wp-post-image" alt="">
      </div>
    </div>
    <div class="p-schedule-detail__main">
      <div class="p-schedule-detail__blcok">
        <div class="p-schedule-detail__date">
          <span class="p-schedule-detail__date-item">05 / 14</span>
          <span class="p-schedule-detail__date-week is-THU">THU</span>
        </div>
        <h3 class="p-schedule-detail__title">
          <span class="p-schedule-detail__title-main">『あいらんど chapter3』</span>
        </h3>
      </div>
      <div class="p-schedule-detail__blcok">
        <div class="c-wp-editor">
          <p>出演：Aivery / しろもん / Falench.</p>
        </div>
      </div>
      <div class="p-schedule-detail__blcok">
        <div class="p-schedule-detail__dl">
          <div class="p-schedule-detail__dt">OPEN</div>
          <div class="p-schedule-detail__dd">17:00</div>
        </div>
        <div class="p-schedule-detail__dl">
          <div class="p-schedule-detail__dt">START</div>
          <div class="p-schedule-detail__dd">17:15</div>
        </div>
        <div class="p-schedule-detail__dl">
          <div class="p-schedule-detail__dt">前方</div>
          <div class="p-schedule-detail__dd">¥3,000</div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""

DETAIL_HTML_NO_PERFORMERS = """\
<html lang="ja">
<body>
<div class="p-schedule-detail__date">
  <span class="p-schedule-detail__date-item">06 / 01</span>
  <span class="p-schedule-detail__date-week is-MON">MON</span>
</div>
<h3 class="p-schedule-detail__title">
  <span class="p-schedule-detail__title-main">Solo Event</span>
</h3>
<div class="p-schedule-detail__dl">
  <div class="p-schedule-detail__dt">OPEN</div>
  <div class="p-schedule-detail__dd">18:30</div>
</div>
<div class="p-schedule-detail__dl">
  <div class="p-schedule-detail__dt">START</div>
  <div class="p-schedule-detail__dd">19:00</div>
</div>
</body>
</html>
"""

DETAIL_HTML_NO_DATE = """\
<html lang="ja">
<body>
<h3 class="p-schedule-detail__title">
  <span class="p-schedule-detail__title-main">Event Without Date</span>
</h3>
</body>
</html>
"""


class TestShibuyaONestCrawler(TestCase):
    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="https://shibuya-o.com/nest/",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="ShibuyaONestCrawler",
        )
        self.crawler = ShibuyaONestCrawler(self.website)

    def test_extract_live_house_info(self):
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "Shibuya O-Nest")
        self.assertEqual(info["name_kana"], "シブヤ オーネスト")
        self.assertEqual(info["name_romaji"], "Shibuya O-Nest")

    def test_find_schedule_link_returns_api_url(self):
        url = self.crawler.find_schedule_link("")
        self.assertEqual(url, "https://shibuya-o.com/wp-json/wp/v2/nest-schedule")

    def test_parse_detail_html_date_and_times(self):
        with patch.object(timezone, "localdate", return_value=timezone.datetime(2026, 5, 1).date()):
            result = self.crawler._parse_detail_html(DETAIL_HTML_FULL, "https://shibuya-o.com/nest/schedule/test/")
        self.assertIsNotNone(result)
        self.assertEqual(result["date"], "2026-05-14")
        self.assertEqual(result["open_time"], "17:00")
        self.assertEqual(result["start_time"], "17:15")

    def test_parse_detail_html_performers(self):
        with patch.object(timezone, "localdate", return_value=timezone.datetime(2026, 5, 1).date()):
            result = self.crawler._parse_detail_html(DETAIL_HTML_FULL, "https://shibuya-o.com/nest/schedule/test/")
        self.assertIsNotNone(result)
        self.assertIn("Aivery", result["performers"])
        self.assertIn("しろもん", result["performers"])
        self.assertIn("Falench.", result["performers"])

    def test_parse_detail_html_event_image(self):
        with patch.object(timezone, "localdate", return_value=timezone.datetime(2026, 5, 1).date()):
            result = self.crawler._parse_detail_html(DETAIL_HTML_FULL, "https://shibuya-o.com/nest/schedule/test/")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("event_image_url"), "https://example.com/flyer.jpg")

    def test_parse_detail_html_no_performers_falls_back_to_event_name(self):
        with patch.object(timezone, "localdate", return_value=timezone.datetime(2026, 6, 1).date()):
            result = self.crawler._parse_detail_html(
                DETAIL_HTML_NO_PERFORMERS, "https://shibuya-o.com/nest/schedule/test/"
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["performers"], ["Solo Event"])

    def test_parse_detail_html_missing_date_returns_none(self):
        result = self.crawler._parse_detail_html(DETAIL_HTML_NO_DATE, "https://shibuya-o.com/nest/schedule/test/")
        self.assertIsNone(result)

    def test_parse_detail_html_year_rollover(self):
        # When crawling in December, January events belong to next year
        with patch.object(timezone, "localdate", return_value=timezone.datetime(2026, 12, 15).date()):
            html = DETAIL_HTML_NO_PERFORMERS.replace("06 / 01", "01 / 10").replace("MON", "SAT")
            result = self.crawler._parse_detail_html(html, "https://shibuya-o.com/nest/schedule/test/")
        self.assertIsNotNone(result)
        self.assertEqual(result["date"], "2027-01-10")

    def test_extract_performance_schedules_returns_empty(self):
        # extract_performance_schedules is not used — process_performance_schedules overrides
        result = self.crawler.extract_performance_schedules("")
        self.assertEqual(result, [])

    def test_fetch_all_schedules_via_api_pagination(self):
        mock_posts_page1 = [
            {"link": "https://shibuya-o.com/nest/schedule/event-a/"},
        ]
        mock_posts_page2 = [
            {"link": "https://shibuya-o.com/nest/schedule/event-b/"},
        ]

        detail_a = DETAIL_HTML_FULL
        detail_b = DETAIL_HTML_NO_PERFORMERS

        def mock_get(url: str, **_kwargs: object) -> MagicMock:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "&page=1" in url:
                resp.json.return_value = mock_posts_page1
                resp.headers = {"X-WP-TotalPages": "2"}
                resp.status_code = 200
            elif "&page=2" in url:
                resp.json.return_value = mock_posts_page2
                resp.headers = {"X-WP-TotalPages": "2"}
                resp.status_code = 200
            elif "event-a" in url:
                resp.text = detail_a
                resp.status_code = 200
            else:
                resp.text = detail_b
                resp.status_code = 200
            return resp

        self.crawler.session.get = mock_get
        with patch.object(timezone, "localdate", return_value=timezone.datetime(2026, 5, 1).date()):
            schedules = self.crawler._fetch_all_schedules_via_api()

        self.assertEqual(len(schedules), 2)
        dates = [s["date"] for s in schedules]
        self.assertIn("2026-05-14", dates)
        self.assertIn("2026-06-01", dates)
