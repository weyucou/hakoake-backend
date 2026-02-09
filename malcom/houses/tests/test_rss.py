import xml.etree.ElementTree as ET
from datetime import date, time, timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from performers.models import Performer

from houses.urls import distill_urlpatterns

from ..feeds import LatestPerformancesFeed
from ..models import LiveHouse, LiveHouseWebsite, PerformanceSchedule, PerformanceScheduleTicketPurchaseInfo


class RSSFeedTestCase(TestCase):
    """Test cases for RSS feed functionality."""

    def setUp(self):
        """Set up test data."""
        # Create test website
        self.website = LiveHouseWebsite.objects.create(url="https://example.com", crawler_class="test_crawler")

        # Create test live house
        self.live_house = LiveHouse.objects.create(
            website=self.website,
            name="Test Venue",
            name_kana="テストベニュー",
            name_romaji="tesuto benyuu",
            address="123 Test Street, Tokyo",
            capacity=200,
            opened_date=date(2020, 1, 1),
        )

        # Create test performers
        self.performer1 = Performer.objects.create(
            name="Test Band 1", name_kana="テストバンド1", name_romaji="tesuto bando 1"
        )

        self.performer2 = Performer.objects.create(
            name="Test Band 2", name_kana="テストバンド2", name_romaji="tesuto bando 2"
        )

        # Create test performances
        today = timezone.now().date()
        tomorrow = today + timedelta(days=1)
        next_week = today + timedelta(days=7)

        self.performance1 = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_name="Rock Night",
            performance_date=tomorrow,
            open_time=time(18, 30),
            start_time=time(19, 0),
            presale_price=2000,
            door_price=2500,
        )
        self.performance1.performers.add(self.performer1, self.performer2)

        self.performance2 = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_name="Jazz Evening",
            performance_date=next_week,
            open_time=time(19, 0),
            start_time=time(19, 30),
            presale_price=3000,
            door_price=3500,
        )
        self.performance2.performers.add(self.performer1)

        # Create ticket info for performance1
        self.ticket_info = PerformanceScheduleTicketPurchaseInfo.objects.create(
            performance=self.performance1,
            ticket_url="https://example.com/tickets",
            ticket_contact_email="tickets@example.com",
            ticket_price=2000,
        )

        self.client = Client()

    def test_rss_feed_url_accessible(self):
        """Test that RSS feed URL is accessible."""
        url = reverse("houses:latest_rss")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/rss+xml; charset=utf-8")

    def test_rss_feed_content_structure(self):
        """Test RSS feed XML structure is valid."""
        url = reverse("houses:latest_rss")
        response = self.client.get(url)

        # Parse XML to ensure it's valid
        root = ET.fromstring(response.content)  # noqa: S314

        # Check RSS structure
        self.assertEqual(root.tag, "rss")
        self.assertEqual(root.attrib["version"], "2.0")

        # Check channel exists
        channel = root.find("channel")
        self.assertIsNotNone(channel)

        # Check required channel elements
        title = channel.find("title")
        self.assertIsNotNone(title)
        self.assertEqual(title.text, "Latest Performance Schedules")

        link = channel.find("link")
        self.assertIsNotNone(link)

        description = channel.find("description")
        self.assertIsNotNone(description)
        self.assertEqual(description.text, "Latest upcoming performances at live houses")

    def test_rss_feed_items_content(self):
        """Test RSS feed items contain correct performance data."""
        url = reverse("houses:latest_rss")
        response = self.client.get(url)

        root = ET.fromstring(response.content)  # noqa: S314
        channel = root.find("channel")
        items = channel.findall("item")

        # Should have 2 items
        self.assertEqual(len(items), 2)

        # Test first item
        first_item = items[0]
        title = first_item.find("title").text
        description = first_item.find("description").text

        self.assertIn("Rock Night", title)
        self.assertIn("Test Venue", title)

        # Check description contains expected information
        self.assertIn("Event: Rock Night", description)
        self.assertIn("Venue: Test Venue", description)
        self.assertIn("Doors: 18:30", description)
        self.assertIn("Start: 19:00", description)
        self.assertIn("Presale: ¥2,000", description)
        self.assertIn("Door: ¥2,500", description)
        self.assertIn("Performers: Test Band 1, Test Band 2", description)
        self.assertIn("Address: 123 Test Street, Tokyo", description)
        self.assertIn("Capacity: 200", description)
        self.assertIn("Tickets: https://example.com/tickets", description)
        self.assertIn("Contact: tickets@example.com", description)

    def test_rss_feed_only_upcoming_performances(self):
        """Test RSS feed only includes upcoming performances."""
        # Create a past performance
        yesterday = timezone.now().date() - timedelta(days=1)
        PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_name="Past Show",
            performance_date=yesterday,
            open_time=time(18, 0),
            start_time=time(19, 0),
        )

        url = reverse("houses:latest_rss")
        response = self.client.get(url)

        # Should not include past performance
        self.assertNotIn("Past Show", response.content.decode())

        root = ET.fromstring(response.content)  # noqa: S314
        channel = root.find("channel")
        items = channel.findall("item")

        # Should still have only 2 items (not 3)
        self.assertEqual(len(items), 2)

    def test_rss_feed_class_methods(self):
        """Test individual methods of the RSS feed class."""
        feed = LatestPerformancesFeed()

        # Test title
        self.assertEqual(feed.title, "Latest Performance Schedules")

        # Test link
        self.assertEqual(feed.link, "/schedule/")

        # Test description
        self.assertEqual(feed.description, "Latest upcoming performances at live houses")

        # Test items method
        items = feed.items()
        self.assertEqual(len(items), 2)

        # Test item_title method
        title = feed.item_title(self.performance1)
        self.assertEqual(title, "Rock Night at Test Venue")

        # Test item_link method
        link = feed.item_link(self.performance1)
        expected_url = reverse(
            "houses:schedule_month",
            args=[self.performance1.performance_date.year, self.performance1.performance_date.month],
        )
        self.assertEqual(link, expected_url)

        # Test item_guid method
        guid = feed.item_guid(self.performance1)
        expected_guid = (
            f"performance-{self.performance1.id}-{self.performance1.performance_date}-{self.performance1.start_time}"
        )
        self.assertEqual(guid, expected_guid)

    def test_rss_feed_performance_without_name(self):
        """Test RSS feed handles performances without performance_name."""
        # Create performance without name
        tomorrow = timezone.now().date() + timedelta(days=1)
        unnamed_performance = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_name="",  # Empty name
            performance_date=tomorrow,
            open_time=time(20, 0),
            start_time=time(20, 30),
        )

        feed = LatestPerformancesFeed()
        title = feed.item_title(unnamed_performance)

        # Should use fallback title
        self.assertEqual(title, "Performance at Test Venue")

    def test_rss_feed_performance_without_prices(self):
        """Test RSS feed handles performances without pricing information."""
        tomorrow = timezone.now().date() + timedelta(days=2)
        no_price_performance = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_name="Free Show",
            performance_date=tomorrow,
            open_time=time(18, 0),
            start_time=time(18, 30),
            presale_price=None,
            door_price=None,
        )

        feed = LatestPerformancesFeed()
        description = feed.item_description(no_price_performance)

        # Should not contain price information
        self.assertNotIn("Presale:", description)
        self.assertNotIn("Door:", description)
        self.assertIn("Event: Free Show", description)

    def test_rss_feed_performance_without_performers(self):
        """Test RSS feed handles performances without performers."""
        tomorrow = timezone.now().date() + timedelta(days=3)
        no_performers_performance = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_name="Open Mic",
            performance_date=tomorrow,
            open_time=time(19, 0),
            start_time=time(19, 30),
        )

        feed = LatestPerformancesFeed()
        description = feed.item_description(no_performers_performance)

        # Should not contain performers section
        self.assertNotIn("Performers:", description)
        self.assertIn("Event: Open Mic", description)

    def test_rss_feed_limit_50_items(self):
        """Test RSS feed limits results to 50 items."""
        # Create many performances
        tomorrow = timezone.now().date() + timedelta(days=1)

        for i in range(60):  # Create 60 performances
            PerformanceSchedule.objects.create(
                live_house=self.live_house,
                performance_name=f"Show {i}",
                performance_date=tomorrow + timedelta(days=i),
                open_time=time(19, 0),
                start_time=time(19, 30),
            )

        feed = LatestPerformancesFeed()
        items = feed.items()

        # Should be limited to 50 items
        self.assertEqual(len(items), 50)

    def test_rss_feed_url_reverse(self):
        """Test RSS feed URL can be reversed."""
        url = reverse("houses:latest_rss")
        self.assertEqual(url, "/latest-rss.xml")

    def test_rss_feed_distill_pattern_exists(self):
        """Test RSS feed distill URL pattern exists."""
        # Check that the RSS distill pattern exists
        distill_names = [pattern.name for pattern in distill_urlpatterns]
        self.assertIn("latest_rss_distill", distill_names)

        # Find the RSS pattern and check its route
        rss_pattern = next((p for p in distill_urlpatterns if p.name == "latest_rss_distill"), None)
        self.assertIsNotNone(rss_pattern)
        self.assertEqual(str(rss_pattern.pattern), "static/latest-rss.xml")
