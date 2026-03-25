from datetime import date, time, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from performers.models import Performer, PerformerSocialLink

from houses.models import LiveHouse, LiveHouseWebsite, PerformanceSchedule, PerformanceScheduleTicketPurchaseInfo


class PerformerDetailViewTestCase(TestCase):
    """Test cases for performer detail view functionality."""

    def setUp(self):
        self.client = Client()

        # Create test data
        self.website = LiveHouseWebsite.objects.create(url="https://test-venue.com", crawler_class="TestCrawler")

        self.live_house = LiveHouse.objects.create(
            website=self.website,
            name="テストハウス",
            name_kana="テストハウス",
            name_romaji="Test House",
            address="東京都渋谷区テスト1-1-1",
            capacity=150,
            opened_date=date(2020, 1, 1),
        )

        self.performer = Performer.objects.create(
            name="テストアーティスト",
            name_kana="テストアーティスト",
            name_romaji="Test Artist",
            website="https://testartist.com",
        )

        # Create social links
        self.twitter_link = PerformerSocialLink.objects.create(
            performer=self.performer, platform="twitter", platform_id="testartist", url="https://twitter.com/testartist"
        )

        self.instagram_link = PerformerSocialLink.objects.create(
            performer=self.performer,
            platform="instagram",
            platform_id="testartist_official",
            url="https://instagram.com/testartist_official",
        )

        # Create performances
        current_date = timezone.now().date()

        # Future performance
        self.future_performance = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_date=current_date + timedelta(days=7),
            open_time=time(18, 30),
            start_time=time(19, 0),
            performance_name="Future Show",
        )
        self.future_performance.performers.add(self.performer)

        # Past performance
        self.past_performance = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_date=current_date - timedelta(days=7),
            open_time=time(18, 30),
            start_time=time(19, 0),
            performance_name="Past Show",
        )
        self.past_performance.performers.add(self.performer)

    def test_performer_detail_view_success(self):
        """Test successful performer detail view rendering."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "テストアーティスト")
        self.assertContains(response, "Test Artist")
        self.assertContains(response, "testartist.com")

        # Check context data
        self.assertEqual(response.context["performer"], self.performer)
        self.assertEqual(len(response.context["social_links"]), 2)
        self.assertEqual(len(response.context["upcoming_performances"]), 1)

    def test_performer_detail_view_not_found(self):
        """Test 404 response for non-existent performer."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": 99999})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_performer_social_links_display(self):
        """Test that social media links are displayed correctly."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        # Check social media platform names
        self.assertContains(response, "Twitter")
        self.assertContains(response, "Instagram")

        # Check platform IDs
        self.assertContains(response, "@testartist")
        self.assertContains(response, "@testartist_official")

        # Check URLs
        self.assertContains(response, "twitter.com/testartist")
        self.assertContains(response, "instagram.com/testartist_official")

    def test_performer_upcoming_performances_only(self):
        """Test that only upcoming performances are shown."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        upcoming_performances = response.context["upcoming_performances"]
        self.assertEqual(len(upcoming_performances), 1)
        self.assertEqual(upcoming_performances[0], self.future_performance)

        # Check that past performance is not included
        performance_dates = [p.performance_date for p in upcoming_performances]
        self.assertNotIn(self.past_performance.performance_date, performance_dates)

    def test_performer_no_upcoming_performances(self):
        """Test performer detail view when no upcoming performances exist."""
        # Delete the future performance
        self.future_performance.delete()

        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "今後の予定はまだありません")
        self.assertEqual(len(response.context["upcoming_performances"]), 0)

    def test_performer_no_social_links(self):
        """Test performer detail view when no social links exist."""
        # Delete all social links
        PerformerSocialLink.objects.filter(performer=self.performer).delete()

        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["social_links"]), 0)
        # The social media section should not be displayed when no links exist
        self.assertNotContains(response, "ソーシャルメディア")

    def test_performer_with_all_social_platforms(self):
        """Test performer with all supported social media platforms."""
        # Create additional social links
        platforms = [
            ("youtube", "testartist", "https://youtube.com/testartist"),
            ("facebook", "testartist", "https://facebook.com/testartist"),
            ("bandcamp", "testartist", "https://testartist.bandcamp.com"),
            ("soundcloud", "testartist", "https://soundcloud.com/testartist"),
            ("spotify", "testartist", "https://open.spotify.com/artist/testartist"),
            ("apple_music", "testartist", "https://music.apple.com/artist/testartist"),
        ]

        for platform, platform_id, url in platforms:
            PerformerSocialLink.objects.create(
                performer=self.performer, platform=platform, platform_id=platform_id, url=url
            )

        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        # Check that all platforms are displayed
        self.assertContains(response, "YouTube")
        self.assertContains(response, "Facebook")
        self.assertContains(response, "Bandcamp")
        self.assertContains(response, "SoundCloud")
        self.assertContains(response, "Spotify")
        self.assertContains(response, "Apple Music")

    def test_performer_shared_performances(self):
        """Test performer with shared performances (multiple performers)."""
        # Create another performer
        other_performer = Performer.objects.create(
            name="共演者", name_kana="キョウエンシャ", name_romaji="Co-Performer"
        )

        # Add other performer to future performance
        self.future_performance.performers.add(other_performer)

        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        # Check that co-performer is shown
        self.assertContains(response, "共演者")
        self.assertContains(response, "co-performers")

    def test_performer_venue_links(self):
        """Test that venue names link to venue detail pages."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        # Check that venue links are present
        venue_url = reverse("houses:venue_detail", kwargs={"venue_id": self.live_house.id})
        self.assertContains(response, venue_url)
        self.assertContains(response, self.live_house.name)

    def test_performer_optional_fields(self):
        """Test performer with minimal data (only required fields)."""
        minimal_performer = Performer.objects.create(
            name="ミニマル",
            name_kana="",  # Optional
            name_romaji="",  # Optional
        )

        url = reverse("houses:performer_detail", kwargs={"performer_id": minimal_performer.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ミニマル")

    def test_performer_performance_names_display(self):
        """Test that performance names are displayed when available."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        # Should show performance name
        self.assertContains(response, "Future Show")

    def test_template_rendering_structure(self):
        """Test that the template renders with expected structure."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        # Check for key CSS classes and elements
        self.assertContains(response, "performer-hero")
        self.assertContains(response, "performer-name")
        self.assertContains(response, "back-link")
        self.assertContains(response, "social-grid")
        self.assertContains(response, "perf-grid")

    def test_back_link_navigation(self):
        """Test that back link points to schedule."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        schedule_url = reverse("houses:schedule_current")
        self.assertContains(response, schedule_url)
        self.assertContains(response, "スケジュールに戻る")


class PerformerTicketInfoTestCase(TestCase):
    """Test cases for performer detail view with ticket information."""

    def setUp(self):
        self.client = Client()

        # Create test data
        website = LiveHouseWebsite.objects.create(url="https://ticket-venue.com", crawler_class="TestCrawler")

        self.live_house = LiveHouse.objects.create(
            website=website,
            name="チケットテストハウス",
            name_kana="チケットテストハウス",
            name_romaji="Ticket Test House",
            address="東京都新宿区チケット1-1-1",
            capacity=200,
            opened_date=date(2021, 1, 1),
        )

        self.performer = Performer.objects.create(
            name="チケットアーティスト", name_kana="チケットアーティスト", name_romaji="Ticket Artist"
        )

        # Create performance with ticket info
        current_date = timezone.now().date()
        self.performance_with_tickets = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_date=current_date + timedelta(days=14),
            open_time=time(18, 0),
            start_time=time(19, 0),
            performance_name="Ticket Show",
        )
        self.performance_with_tickets.performers.add(self.performer)

    def test_performer_with_peatix_tickets(self):
        """Test performer detail view with Peatix ticket links."""
        # Create Peatix ticket info
        PerformanceScheduleTicketPurchaseInfo.objects.create(
            performance=self.performance_with_tickets,
            ticket_url="https://peatix.com/event/12345",
            ticket_price=Decimal("3000.00"),
        )

        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        self.client.get(url)

        # Should contain ticket link but not display it (performer view doesn't show tickets)
        # This tests the model method works correctly
        ticket_info = self.performance_with_tickets.ticket_purchase_info
        service_name, icon = ticket_info.get_ticket_service_info()
        self.assertEqual(service_name, "Peatix")
        self.assertEqual(icon, "fas fa-ticket-alt")

    def test_performer_with_eventbrite_tickets(self):
        """Test performer detail view with Eventbrite ticket links."""
        # Create Eventbrite ticket info
        PerformanceScheduleTicketPurchaseInfo.objects.create(
            performance=self.performance_with_tickets,
            ticket_url="https://eventbrite.com/e/test-event-123",
            ticket_price=Decimal("2500.00"),
        )

        ticket_info = self.performance_with_tickets.ticket_purchase_info
        service_name, icon = ticket_info.get_ticket_service_info()
        self.assertEqual(service_name, "Eventbrite")
        self.assertEqual(icon, "fas fa-calendar-check")

    def test_performer_with_generic_ticket_url(self):
        """Test performer detail view with generic ticket URL."""
        # Create generic ticket info
        PerformanceScheduleTicketPurchaseInfo.objects.create(
            performance=self.performance_with_tickets,
            ticket_url="https://example-venue.com/tickets",
            ticket_price=Decimal("4000.00"),
        )

        ticket_info = self.performance_with_tickets.ticket_purchase_info
        service_name, icon = ticket_info.get_ticket_service_info()
        self.assertEqual(service_name, "チケット購入")
        self.assertEqual(icon, "fas fa-external-link-alt")

    def test_ticket_service_info_all_platforms(self):
        """Test all supported ticket service platforms."""
        test_cases = [
            ("https://peatix.com/event/123", "Peatix", "fas fa-ticket-alt"),
            ("https://eventbrite.co.jp/e/123", "Eventbrite", "fas fa-calendar-check"),
            ("https://tiget.net/events/123", "tiget", "fas fa-ticket-alt"),
            ("https://eplus.jp/event/123", "e+", "fas fa-plus-circle"),
            ("https://pia.jp/t/123", "チケットぴあ", "fas fa-ticket-alt"),
            ("https://l-tike.com/123", "ローソンチケット", "fas fa-store"),
            ("https://cnplayguide.com/123", "CNプレイガイド", "fas fa-play"),
            ("https://ticketport.co.jp/123", "チケットポート", "fas fa-ship"),
            ("https://livepocket.jp/123", "LivePocket", "fas fa-mobile-alt"),
            ("https://zaiko.io/event/123", "ZAIKO", "fas fa-video"),
        ]

        for ticket_url, expected_name, expected_icon in test_cases:
            with self.subTest(ticket_url=ticket_url):
                # Create new performance for each test
                performance = PerformanceSchedule.objects.create(
                    live_house=self.live_house,
                    performance_date=timezone.now().date() + timedelta(days=30),
                    open_time=time(18, 0),
                    start_time=time(19, 0),
                )
                performance.performers.add(self.performer)

                ticket_info = PerformanceScheduleTicketPurchaseInfo.objects.create(
                    performance=performance, ticket_url=ticket_url
                )

                service_name, icon = ticket_info.get_ticket_service_info()
                self.assertEqual(service_name, expected_name)
                self.assertEqual(icon, expected_icon)

    def test_ticket_info_no_url(self):
        """Test ticket info method when no URL is provided."""
        # Create ticket info without URL
        ticket_info = PerformanceScheduleTicketPurchaseInfo.objects.create(
            performance=self.performance_with_tickets, ticket_price=Decimal("2000.00")
        )

        service_name, icon = ticket_info.get_ticket_service_info()
        self.assertIsNone(service_name)
        self.assertIsNone(icon)


class PerformerViewIntegrationTestCase(TestCase):
    """Integration tests for performer views with full data."""

    def setUp(self):
        self.client = Client()

        # Create comprehensive test data
        website = LiveHouseWebsite.objects.create(
            url="https://integration-venue.com", crawler_class="IntegrationCrawler"
        )

        self.live_house = LiveHouse.objects.create(
            website=website,
            name="統合テストライブハウス",
            name_kana="トウゴウテストライブハウス",
            name_romaji="Integration Test Live House",
            address="東京都港区統合2-2-2",
            capacity=300,
            opened_date=date(2022, 6, 1),
        )

        self.performer = Performer.objects.create(
            name="統合テストバンド",
            name_kana="トウゴウテストバンド",
            name_romaji="Integration Test Band",
            website="https://integrationband.com",
        )

        # Create multiple social links
        social_platforms = [
            ("twitter", "integrationband", "https://twitter.com/integrationband"),
            ("instagram", "integrationband_official", "https://instagram.com/integrationband_official"),
            ("youtube", "integrationband", "https://youtube.com/integrationband"),
        ]

        for platform, platform_id, url in social_platforms:
            PerformerSocialLink.objects.create(
                performer=self.performer, platform=platform, platform_id=platform_id, url=url
            )

        # Create multiple performances across time
        current_date = timezone.now().date()

        # Past performances
        for i in range(3):
            past_date = current_date - timedelta(days=30 + i * 10)
            performance = PerformanceSchedule.objects.create(
                live_house=self.live_house,
                performance_date=past_date,
                open_time=time(18, 30),
                start_time=time(19, 0),
                performance_name=f"Past Show {i + 1}",
            )
            performance.performers.add(self.performer)

        # Future performances
        for i in range(5):
            future_date = current_date + timedelta(days=10 + i * 7)
            performance = PerformanceSchedule.objects.create(
                live_house=self.live_house,
                performance_date=future_date,
                open_time=time(18, 0),
                start_time=time(19, 0),
                performance_name=f"Future Show {i + 1}",
            )
            performance.performers.add(self.performer)

    def test_performer_view_comprehensive_data(self):
        """Test performer view with comprehensive data."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # Check performer info
        self.assertContains(response, "統合テストバンド")
        self.assertContains(response, "Integration Test Band")
        self.assertContains(response, "integrationband.com")

        # Check social links
        self.assertEqual(len(response.context["social_links"]), 3)
        self.assertContains(response, "Twitter")
        self.assertContains(response, "Instagram")
        self.assertContains(response, "YouTube")

        # Check upcoming performances (should be limited to 10)
        upcoming = response.context["upcoming_performances"]
        self.assertEqual(len(upcoming), 5)  # We created 5 future performances

        # Verify only future performances are included
        for performance in upcoming:
            self.assertGreaterEqual(performance.performance_date, timezone.now().date())

    def test_performer_view_performance_ordering(self):
        """Test that upcoming performances are properly ordered by date and time."""
        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        upcoming = response.context["upcoming_performances"]

        # Check that performances are ordered by date, then time
        for i in range(len(upcoming) - 1):
            current_perf = upcoming[i]
            next_perf = upcoming[i + 1]

            self.assertLessEqual(
                (current_perf.performance_date, current_perf.start_time),
                (next_perf.performance_date, next_perf.start_time),
            )

    def test_performer_view_maximum_performances_limit(self):
        """Test that performer view limits upcoming performances to reasonable number."""
        # Create many more future performances
        current_date = timezone.now().date()
        for i in range(20):  # Create 20 more performances
            future_date = current_date + timedelta(days=100 + i)
            performance = PerformanceSchedule.objects.create(
                live_house=self.live_house,
                performance_date=future_date,
                open_time=time(20, 0),
                start_time=time(20, 30),
                performance_name=f"Extra Show {i + 1}",
            )
            performance.performers.add(self.performer)

        url = reverse("houses:performer_detail", kwargs={"performer_id": self.performer.id})
        response = self.client.get(url)

        upcoming = response.context["upcoming_performances"]
        # Should be limited to 10 as per view implementation
        self.assertLessEqual(len(upcoming), 10)
