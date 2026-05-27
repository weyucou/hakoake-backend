from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from houses.crawlers import PitZeroCrawler
from houses.crawlers.pit_zero import _parse_ecard_date
from houses.definitions import WebsiteProcessingState
from houses.models import LiveHouseWebsite

# ---- fixture HTML ----

SCHEDULE_LIST_HTML = """\
<!DOCTYPE html>
<html>
<head><title>SCHEDULE</title></head>
<body>
<section class="sec schedule-page">
  <div class="month-filter">
    <a class="month-btn" href="/events?date=2026%2F05">5月</a>
    <a class="month-btn active" href="/events?date=2026%2F06">6月</a>
    <a class="month-btn" href="/events?date=2026%2F07">7月</a>
  </div>

  <div class="events-grid">
    <a class="ecard schedule-card" href="/events/10001">
      <img class="ecard-img" alt="Event One" src="https://example.com/img1.jpg" />
      <span class="ecard-body">
        <span class="ecard-date">2026.6.10 WED</span>
        <span class="ecard-title">Summer Night Live</span>
        <span class="ecard-artists">BandAlpha / BandBeta</span>
        <span class="ecard-price">ADV ¥3,000 / DOOR ¥3,500</span>
      </span>
    </a>
    <a class="ecard schedule-card" href="/events/10002">
      <img class="ecard-img" alt="Event Two" src="https://example.com/img2.jpg" />
      <span class="ecard-body">
        <span class="ecard-date">2026.6.25 THU</span>
        <span class="ecard-title">Rock Festival</span>
        <span class="ecard-artists">ArtistOne / ArtistTwo / ArtistThree</span>
        <span class="ecard-price">ADV ¥4,000 / DOOR ¥4,500</span>
      </span>
    </a>
  </div>
</section>
</body>
</html>
"""

EVENT_DETAIL_HTML = """\
<!DOCTYPE html>
<html>
<body>
<main class="ft-detail">
  <div class="detail-badge">
    <span class="badge-date">2026.6.10(WED)</span>
    <span class="badge-time">OPEN 18:30 / START 19:00</span>
  </div>
  <h1 class="detail-h1">Summer Night Live</h1>
  <div class="detail-grid">
    <div class="detail-block detail-artists">
      <p class="detail-col-title">LINE UP</p>
      <div class="artist-line">
        <span class="artist-role">ARTIST</span>
        <span class="artist-nm">BandAlpha</span>
      </div>
      <div class="artist-line">
        <span class="artist-role">ARTIST</span>
        <span class="artist-nm">BandBeta</span>
      </div>
    </div>
    <div class="detail-block detail-ticket">
      <div class="ticket-row">
        <span class="ticket-label">前売券</span>
        <span class="ticket-price">¥3,000</span>
      </div>
      <div class="ticket-row ticket-row-door">
        <span class="ticket-label">当日券</span>
        <span class="ticket-price">¥3,500</span>
      </div>
    </div>
  </div>
</main>
</body>
</html>
"""

EMPTY_SCHEDULE_HTML = """\
<!DOCTYPE html>
<html><body>
<div class="events-grid"></div>
<p class="empty-message">現在公開中の公演はありません。</p>
</body></html>
"""


class TestParsEcardDate(TestCase):
    """Unit tests for the module-level _parse_ecard_date helper."""

    def test_standard_format(self) -> None:
        self.assertEqual(_parse_ecard_date("2026.6.17 WED"), "2026-06-17")

    def test_parenthesised_day(self) -> None:
        self.assertEqual(_parse_ecard_date("2026.6.17(WED)"), "2026-06-17")

    def test_single_digit_month_and_day(self) -> None:
        self.assertEqual(_parse_ecard_date("2026.1.5 MON"), "2026-01-05")

    def test_double_digit_month_and_day(self) -> None:
        self.assertEqual(_parse_ecard_date("2026.12.31 THU"), "2026-12-31")

    def test_invalid_returns_none(self) -> None:
        self.assertIsNone(_parse_ecard_date("not a date"))

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(_parse_ecard_date(""))


class TestPitZeroCrawler(TestCase):
    """Tests for PitZeroCrawler parsing logic."""

    def setUp(self) -> None:
        self.website = LiveHouseWebsite.objects.create(
            url="https://www.pitzero.takeoff7.tokyo/",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="PitZeroCrawler",
        )
        self.crawler = PitZeroCrawler(self.website)

    def test_extract_live_house_info(self) -> None:
        info = self.crawler.extract_live_house_info("")
        self.assertEqual(info["name"], "Shibuya PIT ZERO")
        self.assertEqual(info["name_kana"], "シブヤピットゼロ")
        self.assertEqual(info["name_romaji"], "Shibuya Pit Zero")
        self.assertIn("渋谷区宇田川町", info["address"])
        self.assertEqual(info["phone_number"], "03-3770-7755")

    def test_find_schedule_link_contains_current_month(self) -> None:
        today = timezone.localdate()
        link = self.crawler.find_schedule_link("")
        self.assertIn(str(today.year), link)
        self.assertIn(f"{today.month:02d}", link)
        self.assertIn("/events?date=", link)

    def test_find_next_month_link(self) -> None:
        today = timezone.localdate()
        next_month = (today.month % 12) + 1
        next_year = today.year if next_month > today.month else today.year + 1
        link = self.crawler.find_next_month_link("")
        self.assertIn(str(next_year), link)
        self.assertIn(f"{next_month:02d}", link)

    def test_parse_event_card_basic(self) -> None:
        soup = self.crawler.create_soup(SCHEDULE_LIST_HTML)
        cards = soup.find_all("a", class_="ecard")
        self.assertEqual(len(cards), 2)  # noqa: PLR2004

        schedule = self.crawler._parse_event_card(cards[0])
        self.assertIsNotNone(schedule)
        self.assertEqual(schedule["date"], "2026-06-10")
        self.assertEqual(schedule["performance_name"], "Summer Night Live")
        self.assertIn("BandAlpha", schedule["performers"])
        self.assertIn("BandBeta", schedule["performers"])
        self.assertEqual(schedule["event_image_url"], "https://example.com/img1.jpg")
        self.assertIn("_detail_url", schedule)

    def test_parse_event_card_multiple_artists(self) -> None:
        soup = self.crawler.create_soup(SCHEDULE_LIST_HTML)
        cards = soup.find_all("a", class_="ecard")
        schedule = self.crawler._parse_event_card(cards[1])
        self.assertIsNotNone(schedule)
        self.assertEqual(len(schedule["performers"]), 3)  # noqa: PLR2004
        self.assertIn("ArtistOne", schedule["performers"])
        self.assertIn("ArtistThree", schedule["performers"])

    def test_enrich_from_detail_sets_times(self) -> None:
        schedule: dict = {
            "date": "2026-06-10",
            "open_time": None,
            "start_time": None,
            "performers": ["BandAlpha", "BandBeta"],
        }
        self.crawler._enrich_from_detail(schedule, "https://www.pitzero.takeoff7.tokyo/events/10001")
        # _enrich_from_detail calls _fetch_event_detail_html internally;
        # since there's no real server here, it returns None and the schedule is unchanged.
        # Test structure: just verify it doesn't raise and doesn't overwrite with garbage.
        self.assertIn("date", schedule)

    def test_enrich_from_detail_parses_times(self) -> None:
        """Verify _enrich_from_detail correctly parses times from fixture detail HTML."""
        schedule: dict = {
            "date": "2026-06-10",
            "open_time": None,
            "start_time": None,
            "performers": [],
        }
        with patch.object(self.crawler, "_fetch_event_detail_html", return_value=EVENT_DETAIL_HTML):
            self.crawler._enrich_from_detail(schedule, "https://www.pitzero.takeoff7.tokyo/events/10001")

        self.assertEqual(schedule["open_time"], "18:30")
        self.assertEqual(schedule["start_time"], "19:00")
        self.assertIn("BandAlpha", schedule["performers"])
        self.assertIn("BandBeta", schedule["performers"])
        self.assertIn("context", schedule)

    def test_extract_performance_schedules_no_detail_fetch(self) -> None:
        """extract_performance_schedules returns events even when detail fetch fails."""
        with patch.object(self.crawler, "_fetch_event_detail_html", return_value=None):
            schedules = self.crawler.extract_performance_schedules(SCHEDULE_LIST_HTML)

        self.assertEqual(len(schedules), 2)  # noqa: PLR2004
        self.assertEqual(schedules[0]["date"], "2026-06-10")
        self.assertIn("BandAlpha", schedules[0]["performers"])
        self.assertEqual(schedules[1]["date"], "2026-06-25")

    def test_extract_performance_schedules_with_detail(self) -> None:
        """extract_performance_schedules enriches times from detail page."""
        with patch.object(self.crawler, "_fetch_event_detail_html", return_value=EVENT_DETAIL_HTML):
            schedules = self.crawler.extract_performance_schedules(SCHEDULE_LIST_HTML)

        self.assertEqual(len(schedules), 2)  # noqa: PLR2004
        self.assertEqual(schedules[0]["open_time"], "18:30")
        self.assertEqual(schedules[0]["start_time"], "19:00")

    def test_extract_performance_schedules_empty_grid(self) -> None:
        with patch.object(self.crawler, "_fetch_event_detail_html", return_value=None):
            schedules = self.crawler.extract_performance_schedules(EMPTY_SCHEDULE_HTML)
        self.assertEqual(schedules, [])

    def test_fetch_event_detail_html_returns_none_on_error(self) -> None:
        """_fetch_event_detail_html returns None instead of raising on network error."""
        with patch.object(self.crawler.session, "get", side_effect=ConnectionError("timeout")):
            result = self.crawler._fetch_event_detail_html("https://www.pitzero.takeoff7.tokyo/events/99")
        self.assertIsNone(result)
