from unittest.mock import patch

from django.test import TestCase

from houses.crawlers import WarpCrawler
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

HOMEPAGE_HTML = """\
<!DOCTYPE html>
<html lang="ja">
<head><title>ライブハウス吉祥寺ワープ / LIVE HOUSE KICHIJOJI WARP</title></head>
<body>
<article data-aos="fade-up">
  <a href="http://warp.rinky.info/schedules/2026-07/10001.html">
    <section><img alt="July Event 1" class="lazyload" data-src="x.jpg"/></section>
  </a>
</article>
<article data-aos="fade-up">
  <a href="http://warp.rinky.info/schedules/2026-07/10002.html">
    <section><img alt="July Event 2" class="lazyload" data-src="x.jpg"/></section>
  </a>
</article>
<article data-aos="fade-up">
  <a href="http://warp.rinky.info/schedules/2026-08/10003.html">
    <section><img alt="August Event" class="lazyload" data-src="x.jpg"/></section>
  </a>
</article>
</body>
</html>
"""

EVENT_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="ja">
<head><title>2026.07.05(SUN) | SCHEDULES | ライブハウス吉祥寺ワープ</title></head>
<body>
<section class="schedules-detail sun">
  <h4>夏のライブ「Vol.1」</h4>
  <section>
    <div class="w-flyer">BandAlpha<br/>
      BandBeta<br/>
      BandGamma<br/>
      and more...<div class="detail-texts"></div>
      <section class="notes-wrapper">
        <p>OPEN / START<br/><span class="strong">18:00 / 18:30</span></p>
      </section>
    </div>
  </section>
</section>
</body>
</html>
"""

EVENT_PAGE_HTML_2 = """\
<!DOCTYPE html>
<html lang="ja">
<head><title>2026.07.12(SAT) | SCHEDULES | ライブハウス吉祥寺ワープ</title></head>
<body>
<section class="schedules-detail sat">
  <h4>夏のライブ「Vol.2」</h4>
  <section>
    <div class="w-flyer">BandDelta<br/>
      BandEpsilon<br/>
      <section class="notes-wrapper">
        <p>OPEN / START<br/><span class="strong">TBA / TBA</span></p>
      </section>
    </div>
  </section>
</section>
</body>
</html>
"""


class TestWarpCrawler(TestCase):
    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="http://warp.rinky.info/",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="WarpCrawler",
        )
        self.crawler = WarpCrawler(self.website)

    def test_extract_live_house_info(self):
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "WARP")

    def test_find_schedule_link(self):
        self.assertEqual(self.crawler.find_schedule_link(""), "http://warp.rinky.info/")

    def test_extract_event_urls_filters_by_month(self):
        import datetime

        with patch("houses.crawlers.warp.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 7, 1)
            soup = self.crawler.create_soup(HOMEPAGE_HTML)
            urls = self.crawler._extract_event_urls(soup, "2026-07")

        self.assertEqual(len(urls), 2)
        self.assertIn("http://warp.rinky.info/schedules/2026-07/10001.html", urls)
        self.assertIn("http://warp.rinky.info/schedules/2026-07/10002.html", urls)
        self.assertNotIn("http://warp.rinky.info/schedules/2026-08/10003.html", urls)

    def test_parse_event_page_extracts_date_and_performers(self):
        schedule = self.crawler._parse_event_page(EVENT_PAGE_HTML, "http://x/10001.html")
        self.assertIsNotNone(schedule)
        self.assertEqual(schedule["date"], "2026-07-05")
        self.assertEqual(schedule["open_time"], "18:00")
        self.assertEqual(schedule["start_time"], "18:30")
        self.assertIn("BandAlpha", schedule["performers"])
        self.assertIn("BandBeta", schedule["performers"])
        self.assertIn("BandGamma", schedule["performers"])
        self.assertNotIn("and more...", schedule["performers"])
        self.assertEqual(schedule["performance_name"], "夏のライブ「Vol.1」")

    def test_parse_event_page_tba_times_are_none(self):
        schedule = self.crawler._parse_event_page(EVENT_PAGE_HTML_2, "http://x/10002.html")
        self.assertIsNotNone(schedule)
        self.assertIsNone(schedule["open_time"])
        self.assertIsNone(schedule["start_time"])

    def test_extract_performance_schedules_fetches_event_pages(self):
        import datetime

        pages = {
            "http://warp.rinky.info/schedules/2026-07/10001.html": EVENT_PAGE_HTML,
            "http://warp.rinky.info/schedules/2026-07/10002.html": EVENT_PAGE_HTML_2,
        }

        with patch("houses.crawlers.warp.timezone") as mock_tz:
            mock_tz.localdate.return_value = datetime.date(2026, 7, 1)
            with patch.object(self.crawler, "fetch_page", side_effect=lambda url: pages[url]):
                schedules = self.crawler.extract_performance_schedules(HOMEPAGE_HTML)

        self.assertEqual(len(schedules), 2)
        dates = [s["date"] for s in schedules]
        self.assertIn("2026-07-05", dates)
        self.assertIn("2026-07-12", dates)
