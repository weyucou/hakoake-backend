"""Tests for Option B fix: pending social links buffered on unsaved performers."""

from unittest.mock import MagicMock

from django.test import TestCase
from houses.crawlers.crawler import LiveHouseWebsiteCrawler

from performers.models import Performer, PerformerSocialLink


class _TestCrawler(LiveHouseWebsiteCrawler):
    def extract_live_house_info(self, html_content: str) -> dict:  # type: ignore[override]
        return {}

    def extract_performance_schedules(self, html_content: str, live_house: object, source_url: str = "") -> list:  # type: ignore[override]
        return []


class TestHasValidOnlinePresencePending(TestCase):
    """has_valid_online_presence() should honour _pending_social_links on unsaved performers."""

    def _make_unsaved_performer(self) -> Performer:
        return Performer(name="Test Band", name_kana="テスト", name_romaji="tesuto")

    def test_no_presence_returns_false(self) -> None:
        p = self._make_unsaved_performer()
        self.assertFalse(p.has_valid_online_presence())

    def test_pending_valid_platform_returns_true(self) -> None:
        p = self._make_unsaved_performer()
        p._pending_social_links = [
            {"platform": "instagram", "platform_id": "testband", "url": "https://instagram.com/testband"}
        ]
        self.assertTrue(p.has_valid_online_presence())

    def test_pending_youtube_still_counts(self) -> None:
        p = self._make_unsaved_performer()
        p._pending_social_links = [
            {"platform": "youtube", "platform_id": "UCabc", "url": "https://youtube.com/c/testband"}
        ]
        self.assertTrue(p.has_valid_online_presence())

    def test_pending_with_empty_url_returns_false(self) -> None:
        p = self._make_unsaved_performer()
        p._pending_social_links = [{"platform": "twitter", "platform_id": "", "url": ""}]
        self.assertFalse(p.has_valid_online_presence())

    def test_pending_with_unknown_platform_returns_false(self) -> None:
        p = self._make_unsaved_performer()
        p._pending_social_links = [
            {"platform": "unknown_platform", "platform_id": "x", "url": "https://unknown.example.com/x"}
        ]
        self.assertFalse(p.has_valid_online_presence())

    def test_website_still_validates_without_pending(self) -> None:
        p = self._make_unsaved_performer()
        p.website = "https://testband.com"
        self.assertTrue(p.has_valid_online_presence())


class TestUpdatePerformerSocialLinksBuffering(TestCase):
    """_update_performer_social_links buffers for unsaved performers instead of hitting the DB."""

    def setUp(self) -> None:
        self.crawler = _TestCrawler.__new__(_TestCrawler)
        self.crawler.session = MagicMock()
        self.crawler.timeout = 10

    def _make_unsaved_performer(self) -> Performer:
        return Performer(name="Test Band", name_kana="テスト", name_romaji="tesuto")

    def _sample_links(self) -> list[dict]:
        return [
            {"platform": "instagram", "platform_id": "testband", "url": "https://instagram.com/testband"},
            {"platform": "youtube", "platform_id": "UCabc", "url": "https://youtube.com/c/testband"},
        ]

    def test_unsaved_performer_buffers_links(self) -> None:
        p = self._make_unsaved_performer()
        self.crawler._update_performer_social_links(p, self._sample_links())
        # YouTube excluded from buffer; instagram included
        self.assertTrue(hasattr(p, "_pending_social_links"))
        platforms = [link["platform"] for link in p._pending_social_links]
        self.assertIn("instagram", platforms)
        self.assertNotIn("youtube", platforms)

    def test_unsaved_performer_no_db_write(self) -> None:
        p = self._make_unsaved_performer()
        self.crawler._update_performer_social_links(p, self._sample_links())
        self.assertEqual(PerformerSocialLink.objects.count(), 0)

    def test_pending_links_accumulate_across_calls(self) -> None:
        p = self._make_unsaved_performer()
        self.crawler._update_performer_social_links(
            p, [{"platform": "instagram", "platform_id": "a", "url": "https://instagram.com/a"}]
        )
        self.crawler._update_performer_social_links(
            p, [{"platform": "twitter", "platform_id": "b", "url": "https://twitter.com/b"}]
        )
        platforms = {link["platform"] for link in p._pending_social_links}
        self.assertEqual(platforms, {"instagram", "twitter"})

    def test_saved_performer_writes_to_db(self) -> None:
        p = Performer.objects.create(name="DB Band", name_kana="テスト", name_romaji="tesuto2")
        self.crawler._update_performer_social_links(
            p, [{"platform": "instagram", "platform_id": "dbband", "url": "https://instagram.com/dbband"}]
        )
        self.assertEqual(PerformerSocialLink.objects.filter(performer=p).count(), 1)
