from datetime import date, datetime
from unittest.mock import MagicMock, Mock, patch

from django.test import TestCase
from performers.models import Performer

from ..crawlers import CrawlerRegistry, LaMamaCrawler, LoftProjectShelterCrawler
from ..definitions import WebsiteProcessingState
from ..models import LiveHouse, LiveHouseWebsite, PerformanceSchedule

_MINIMAL_SVG = b"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
  <rect width="100" height="100" fill="red"/>
</svg>"""

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class TestLiveHouseWebsiteCrawler(TestCase):
    """Test cases for LiveHouseWebsiteCrawler base functionality."""

    def setUp(self):
        """Set up test data."""
        self.website = LiveHouseWebsite.objects.create(
            url="https://test.example.com", state=WebsiteProcessingState.NOT_STARTED, crawler_class="TestCrawler"
        )

    def test_create_or_update_live_house_with_existing(self):
        """Test updating an existing LiveHouse."""
        crawler = LoftProjectShelterCrawler(self.website)

        # Create initial live house
        initial_data = {
            "name": "Test Venue",
            "name_kana": "TestKana",
            "name_romaji": "Test Venue",
            "address": "Old Address",
            "phone_number": "03-1234-5678",
            "capacity": 100,
            "opened_date": "2020-01-01",
        }
        live_house = crawler.create_or_update_live_house(initial_data)
        initial_id = live_house.id

        # Update with new data
        updated_data = {
            "name": "Test Venue Updated",
            "name_kana": "TestKana",
            "name_romaji": "Test Venue",
            "address": "New Address",
            "phone_number": "03-9876-5432",
            "capacity": 200,
            "opened_date": "2020-01-01",
        }
        updated_house = crawler.create_or_update_live_house(updated_data)

        # Verify it's the same object, just updated
        self.assertEqual(initial_id, updated_house.id)
        self.assertEqual(updated_house.address, "New Address")
        self.assertEqual(updated_house.capacity, 200)
        self.assertEqual(LiveHouse.objects.count(), 1)

    def test_create_performance_schedule_string_parsing(self):
        """Test performer string parsing logic."""
        crawler = LoftProjectShelterCrawler(self.website)
        live_house = LiveHouse.objects.create(
            website=self.website,
            name="Test Venue",
            name_kana="TestKana",
            name_romaji="Test",
            address="Tokyo",
            capacity=200,
            opened_date=date(2020, 1, 1),
        )

        # Mock _search_for_performer_details to skip online validation
        with patch.object(crawler, "_search_for_performer_details", return_value=None):
            # Test with a single performer list
            data = {"date": "2024-12-01", "open_time": "18:00", "start_time": "18:30", "performers": ["Artist A"]}

            performance = crawler.create_performance_schedule(live_house, data)
            performer_names = list(performance.performers.values_list("name", flat=True))

            self.assertEqual(performer_names, ["Artist A"])

            # Clean up for next test
            performance.delete()
            Performer.objects.all().delete()

    @patch("requests.Session.get")
    def test_process_performance_schedules_with_pagination(self, mock_get):  # noqa: ANN001
        """Test that process_performance_schedules handles pagination correctly."""
        crawler = LoftProjectShelterCrawler(self.website)
        live_house = LiveHouse.objects.create(
            website=self.website,
            name="Test Venue",
            name_kana="TestKana",
            name_romaji="Test",
            address="Tokyo",
            capacity=200,
            opened_date=date(2020, 1, 1),
        )

        # Use a date pattern that the crawler can parse (YYYY MM DD format)
        current_year = datetime.now().year  # noqa: DTZ005
        next_year = current_year + 1

        # Mock current month page with proper HTML structure
        current_month_html = f"""
        <html><body>
            <div class="schedule">
                {current_year} 12 15
                OPEN 18:00 / START 18:30
                Current Month Band
            </div>
            <a href="/next">次月</a>
        </body></html>
        """

        # Mock next month page
        next_month_html = f"""
        <html><body>
            <div class="schedule">
                {next_year} 01 10
                OPEN 19:00 / START 19:30
                Next Month Band
            </div>
        </body></html>
        """

        # Set up mock responses
        mock_responses = [Mock(), Mock()]
        mock_responses[0].text = current_month_html
        mock_responses[0].raise_for_status = Mock()
        mock_responses[1].text = next_month_html
        mock_responses[1].raise_for_status = Mock()
        mock_get.side_effect = mock_responses

        # Mock performer validation to skip online presence check
        with patch.object(crawler, "_search_for_performer_details", return_value=None):
            # Process schedules
            crawler.process_performance_schedules("https://test.com/schedule", live_house)

        # Verify both months were processed
        schedules = PerformanceSchedule.objects.all()
        self.assertEqual(schedules.count(), 2)

        # Verify performers from both pages
        all_performers = Performer.objects.all()
        performer_names = set(all_performers.values_list("name", flat=True))
        self.assertIn("Current Month Band", performer_names)
        self.assertIn("Next Month Band", performer_names)


class TestLoftProjectShelterCrawler(TestCase):
    """Test cases for Loft Project Shelter crawler parsing logic."""

    def setUp(self):
        """Set up test data."""
        self.website = LiveHouseWebsite.objects.create(
            url="https://www.loft-prj.co.jp/schedule/shelter",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="LoftProjectShelterCrawler",
        )
        self.crawler = LoftProjectShelterCrawler(self.website)

    def test_extract_performance_schedules_date_parsing(self):
        """Test date parsing logic with year rollover."""
        # Mock it being December
        with patch("houses.crawlers.loft_project_shelter.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 12, 1)  # noqa: DTZ001
            mock_datetime.strptime = datetime.strptime

            # Use the YYYY MM DD format that the crawler parses
            html = """
            <html><body>
                <div class="schedule">
                    2024 12 15
                    OPEN 18:00 / START 18:30
                    December Band
                </div>
                <div class="schedule">
                    2025 01 05
                    OPEN 19:00 / START 19:30
                    January Band
                </div>
            </body></html>
            """

            schedules = self.crawler.extract_performance_schedules(html)

            # Should parse dates correctly
            self.assertEqual(len(schedules), 2)
            self.assertEqual(schedules[0]["date"], "2024-12-15")
            self.assertEqual(schedules[1]["date"], "2025-01-05")

    def test_extract_performance_schedules_time_format_variations(self):
        """Test various time format extractions."""
        current_year = datetime.now().year  # noqa: DTZ005

        html = f"""
        <html><body>
            <div class="schedule">
                {current_year} 12 01
                OPEN 18:00 / START 18:30
                Band A
            </div>
            <div class="schedule">
                {current_year} 12 02
                開場 19:00 / 開演 19:30
                Band B
            </div>
            <div class="schedule">
                {current_year} 12 03
                17:30 / 18:00
                Band C
            </div>
            <div class="schedule">
                {current_year} 12 04
                No time info here
                Band D
            </div>
        </body></html>
        """

        schedules = self.crawler.extract_performance_schedules(html)

        # Check each format was parsed correctly
        self.assertEqual(len(schedules), 4)
        self.assertEqual(schedules[0]["open_time"], "18:00")
        self.assertEqual(schedules[0]["start_time"], "18:30")

        self.assertEqual(schedules[1]["open_time"], "19:00")
        self.assertEqual(schedules[1]["start_time"], "19:30")

        self.assertEqual(schedules[2]["open_time"], "17:30")
        self.assertEqual(schedules[2]["start_time"], "18:00")

        # Default times when not found
        self.assertEqual(schedules[3]["open_time"], "18:00")
        self.assertEqual(schedules[3]["start_time"], "18:30")

    def test_extract_performance_schedules_performer_filtering(self):
        """Test performer name filtering logic."""
        current_year = datetime.now().year  # noqa: DTZ005

        html = f"""
        <html><body>
            <div class="schedule">
                {current_year} 12 01
                OPEN 18:00 / START 18:30
                Real Band / Another Band / Third Band
            </div>
        </body></html>
        """

        schedules = self.crawler.extract_performance_schedules(html)

        # Should include valid band names
        performers = schedules[0]["performers"]
        self.assertIn("Real Band", performers)
        self.assertIn("Another Band", performers)
        self.assertIn("Third Band", performers)


class TestLaMamaCrawler(TestCase):
    """Test cases for La Mama crawler parsing logic."""

    def setUp(self):
        """Set up test data."""
        self.website = LiveHouseWebsite.objects.create(
            url="https://www.lamama.net/", state=WebsiteProcessingState.NOT_STARTED, crawler_class="LaMamaCrawler"
        )
        self.crawler = LaMamaCrawler(self.website)

    def test_extract_performance_schedules_lamama_format(self):
        """Test La.mama specific HTML format parsing."""
        # La.mama uses <a class="pickup_btn schedule"> with data-schedule attribute
        html = """
        <html><body>
            <a class="pickup_btn schedule" data-schedule="2024-12-25">
                <p class="event">Christmas Live</p>
                <p class="member">Christmas Band / Holiday Group</p>
            </a>
            <a class="pickup_btn schedule" data-schedule="2025-01-03">
                <p class="event">New Year Show</p>
                <p class="member">New Year Band</p>
            </a>
        </body></html>
        """

        schedules = self.crawler.extract_performance_schedules(html)

        self.assertEqual(len(schedules), 2)
        self.assertEqual(schedules[0]["date"], "2024-12-25")
        self.assertEqual(schedules[1]["date"], "2025-01-03")
        self.assertIn("Christmas Band", schedules[0]["performers"])
        self.assertIn("New Year Band", schedules[1]["performers"])

    def test_extract_live_house_info_capacity_parsing(self):
        """Test capacity format extraction with Japanese patterns."""
        test_cases = [
            ("300人", 300),
            ("250名", 250),
        ]

        for capacity_text, expected_capacity in test_cases:
            html = f"""
            <html><body>
                <section class="about">
                    <p>収容人数: {capacity_text}</p>
                </section>
            </body></html>
            """

            info = self.crawler.extract_live_house_info(html)
            self.assertEqual(info["capacity"], expected_capacity)

    def test_extract_performance_schedules_performer_cleaning(self):
        """Test performer name cleaning logic with La.mama format."""
        html = """
        <html><body>
            <a class="pickup_btn schedule" data-schedule="2024-12-01">
                <p class="event">Test Event</p>
                <p class="member">Band A (from Tokyo) / Band B [guest]</p>
            </a>
        </body></html>
        """

        schedules = self.crawler.extract_performance_schedules(html)
        performers = schedules[0]["performers"]

        # Should clean brackets and their contents
        self.assertIn("Band A", performers)
        self.assertIn("Band B", performers)

        # Should not include bracketed content
        self.assertNotIn("Band A (from Tokyo)", performers)
        self.assertNotIn("Band B [guest]", performers)


class TestCrawlerRegistry(TestCase):
    """Test cases for CrawlerRegistry."""

    def setUp(self):
        """Clear registry before each test."""
        CrawlerRegistry._crawlers.clear()
        # Re-register our crawlers
        CrawlerRegistry._crawlers["LoftProjectShelterCrawler"] = LoftProjectShelterCrawler
        CrawlerRegistry._crawlers["LaMamaCrawler"] = LaMamaCrawler

    def test_run_invalid_crawler(self):
        """Test running non-existent crawler raises error with correct message."""
        website = LiveHouseWebsite.objects.create(
            url="https://test.com", state=WebsiteProcessingState.NOT_STARTED, crawler_class="NonExistentCrawler"
        )

        with self.assertRaises(ValueError) as cm:
            CrawlerRegistry.run_crawler(website)

        self.assertEqual(str(cm.exception), "No crawler found for class: NonExistentCrawler")


class TestCrawlerStateManagement(TestCase):
    """Test crawler state management during execution."""

    @patch("requests.Session.get")
    def test_crawler_atomic_transaction_on_failure(self, mock_get):  # noqa: ANN001
        """Test that state is set to FAILED on exception."""
        website = LiveHouseWebsite.objects.create(
            url="https://test.com", state=WebsiteProcessingState.NOT_STARTED, crawler_class="LoftProjectShelterCrawler"
        )

        # Make extract_live_house_info fail
        crawler = LoftProjectShelterCrawler(website)

        # Mock successful page fetch
        mock_response = Mock()
        mock_response.text = "<html><title>Test</title></html>"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Mock method to raise exception
        with (
            patch.object(crawler, "extract_live_house_info", side_effect=Exception("Parse error")),
        ):
            # Run should handle the exception internally
            crawler.run()

        # State should be FAILED due to exception handling in run()
        website.refresh_from_db()
        self.assertEqual(website.state, WebsiteProcessingState.FAILED)


class TestIsValidPerformerNameJunkPatterns(TestCase):
    """Test new junk rejection patterns in _is_valid_performer_name."""

    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="https://test.example.com",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="LoftProjectShelterCrawler",
        )
        self.crawler = LoftProjectShelterCrawler(self.website)

    def test_rejects_url(self):
        self.assertFalse(self.crawler._is_valid_performer_name("https://example.com/band"))

    def test_rejects_html_extension(self):
        self.assertFalse(self.crawler._is_valid_performer_name("schedule.html"))

    def test_rejects_php_extension(self):
        self.assertFalse(self.crawler._is_valid_performer_name("event.php"))

    def test_rejects_path_like_string(self):
        self.assertFalse(self.crawler._is_valid_performer_name("123/page"))

    def test_rejects_bare_and_more(self):
        self.assertFalse(self.crawler._is_valid_performer_name("and more..."))

    def test_rejects_ticket_purchase_text(self):
        self.assertFalse(self.crawler._is_valid_performer_name("チケット予約はこちら"))

    def test_rejects_instrument_prefix(self):
        self.assertFalse(self.crawler._is_valid_performer_name("Vocals：Taro"))

    def test_rejects_food_prefix_fullwidth(self):
        self.assertFalse(self.crawler._is_valid_performer_name("FOOD＞special menu"))

    def test_accepts_anymore(self):
        """'Anymore' is a valid band name, not 'and more'."""
        self.assertTrue(self.crawler._is_valid_performer_name("Anymore"))

    def test_accepts_valid_japanese_name(self):
        self.assertTrue(self.crawler._is_valid_performer_name("東京スカパラダイスオーケストラ"))

    def test_accepts_valid_english_name(self):
        self.assertTrue(self.crawler._is_valid_performer_name("The Blue Hearts"))


class TestCleanPerformerName(TestCase):
    """Test BOM stripping and 'and more' suffix removal in _clean_performer_name."""

    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="https://test.example.com",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="LoftProjectShelterCrawler",
        )
        self.crawler = LoftProjectShelterCrawler(self.website)

    def test_strips_bom(self):
        self.assertEqual(self.crawler._clean_performer_name("\ufeffBand Name"), "Band Name")

    def test_strips_and_more_suffix(self):
        self.assertEqual(self.crawler._clean_performer_name("Band A and more"), "Band A")

    def test_strips_and_more_with_ellipsis(self):
        self.assertEqual(self.crawler._clean_performer_name("Band A...and more"), "Band A")

    def test_strips_and_more_with_unicode_ellipsis(self):
        self.assertEqual(self.crawler._clean_performer_name("Band A…and more guests"), "Band A")

    def test_strips_and_more_case_insensitive(self):
        self.assertEqual(self.crawler._clean_performer_name("Band A AND MORE"), "Band A")

    def test_preserves_normal_name(self):
        self.assertEqual(self.crawler._clean_performer_name("Band Anymore"), "Band Anymore")


class TestSaveEventImageSvgConversion(TestCase):
    """Regression tests for SVG-to-PNG conversion in _save_event_image."""

    def setUp(self):
        self.website = LiveHouseWebsite.objects.create(
            url="https://test.example.com",
            state=WebsiteProcessingState.NOT_STARTED,
            crawler_class="LoftProjectShelterCrawler",
        )
        self.crawler = LoftProjectShelterCrawler(self.website)

    def _make_mock_performance(self):  # noqa: ANN202
        event_image = MagicMock()
        event_image.__bool__.return_value = False
        performance = Mock()
        performance.event_image = event_image
        return performance

    @patch("requests.Session.get")
    def test_svg_by_content_type_converted_to_png(self, mock_get):  # noqa: ANN001
        """SVG detected via image/svg+xml Content-Type is converted to PNG before saving."""
        mock_response = Mock()
        mock_response.content = _MINIMAL_SVG
        mock_response.headers = {"Content-Type": "image/svg+xml"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        performance = self._make_mock_performance()
        self.crawler._save_event_image("https://example.com/flyer.svg", performance)

        performance.event_image.save.assert_called_once()
        saved_filename, saved_content = performance.event_image.save.call_args[0]
        self.assertTrue(saved_filename.endswith(".png"), f"Expected .png filename, got: {saved_filename}")
        self.assertEqual(saved_content.read()[:8], _PNG_MAGIC)

    @patch("requests.Session.get")
    def test_svg_by_extension_converted_to_png(self, mock_get):  # noqa: ANN001
        """SVG detected via .svg file extension is converted to PNG before saving."""
        mock_response = Mock()
        mock_response.content = _MINIMAL_SVG
        mock_response.headers = {"Content-Type": "application/octet-stream"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        performance = self._make_mock_performance()
        self.crawler._save_event_image("https://example.com/menu_twitter.svg", performance)

        performance.event_image.save.assert_called_once()
        saved_filename, saved_content = performance.event_image.save.call_args[0]
        self.assertTrue(saved_filename.endswith(".png"), f"Expected .png filename, got: {saved_filename}")
        self.assertEqual(saved_content.read()[:8], _PNG_MAGIC)
