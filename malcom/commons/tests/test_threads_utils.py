"""Tests for Threads post-building helpers and create_thread_post."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase

from commons.threads_utils import (
    THREADS_MAX_CHARS,
    _build_monthly_thread_text,
    _build_weekly_thread_text,
    _truncate_to_threads_limit,
    create_thread_post,
)


class TestTruncateToThreadsLimit(TestCase):
    def test_short_text_unchanged(self) -> None:
        result = _truncate_to_threads_limit("Hello", "https://example.com")
        self.assertEqual(result, "Hello\nhttps://example.com")
        self.assertLessEqual(len(result), THREADS_MAX_CHARS)

    def test_url_always_present_after_truncation(self) -> None:
        url = "https://www.youtube.com/playlist?list=PLtest123"
        long_lines = "\n".join(f"{i}. 2026-01-0{i % 9 + 1} (Mon) BandName{i} @ Venue{i}" for i in range(1, 20))
        result = _truncate_to_threads_limit(long_lines, url)
        self.assertLessEqual(len(result), THREADS_MAX_CHARS)
        self.assertIn(url, result)

    def test_truncation_ends_with_ellipsis_before_url(self) -> None:
        url = "https://www.youtube.com/playlist?list=PLtest123"
        long_text = "A" * 400 + "\n" + "B" * 200
        result = _truncate_to_threads_limit(long_text, url)
        self.assertLessEqual(len(result), THREADS_MAX_CHARS)
        self.assertIn("…", result)
        self.assertTrue(result.endswith(url))

    def test_exactly_at_limit_not_truncated(self) -> None:
        url = "https://x.com/p"
        # Build text so total is exactly THREADS_MAX_CHARS
        overhead = len(f"\n{url}")
        text = "x" * (THREADS_MAX_CHARS - overhead)
        result = _truncate_to_threads_limit(text, url)
        self.assertEqual(len(result), THREADS_MAX_CHARS)
        self.assertNotIn("…", result)


class _FakePlaylist:
    """Minimal duck-typed playlist for text-building tests."""

    def __init__(self, playlist_date: date, playlist_id: str, playlist_url: str = "") -> None:
        self.date = playlist_date
        self.youtube_playlist_id = playlist_id
        self.youtube_playlist_url = playlist_url


class TestBuildWeeklyThreadText(TestCase):
    def test_includes_url_from_youtube_playlist_url(self) -> None:
        playlist = _FakePlaylist(date(2026, 3, 31), "PLtest", "https://www.youtube.com/playlist?list=PLtest")
        lineup_lines = ["1. 2026-03-31 (Tue) TestBand @ Shibuya Club"]
        result = _build_weekly_thread_text(playlist, lineup_lines)
        self.assertIn("https://www.youtube.com/playlist?list=PLtest", result)

    def test_falls_back_to_constructed_url_when_no_playlist_url(self) -> None:
        playlist = _FakePlaylist(date(2026, 3, 31), "PLfallback", "")
        lineup_lines = ["1. 2026-03-31 (Tue) TestBand @ Shibuya Club"]
        result = _build_weekly_thread_text(playlist, lineup_lines)
        self.assertIn("PLfallback", result)

    def test_within_character_limit(self) -> None:
        playlist = _FakePlaylist(date(2026, 3, 31), "PLtest", "https://www.youtube.com/playlist?list=PLtest")
        lineup_lines = [f"{i}. 2026-03-31 (Tue) Band{i:02d} @ Venue{i:02d}" for i in range(1, 20)]
        result = _build_weekly_thread_text(playlist, lineup_lines)
        self.assertLessEqual(len(result), THREADS_MAX_CHARS)


class TestBuildMonthlyThreadText(TestCase):
    def test_includes_month_in_text(self) -> None:
        playlist = _FakePlaylist(date(2026, 4, 1), "PLmonth", "https://www.youtube.com/playlist?list=PLmonth")
        lineup_lines = ["1. 2026-04-10 (Fri) TestBand @ Shinjuku Club"]
        result = _build_monthly_thread_text(playlist, lineup_lines)
        self.assertIn("April 2026", result)
        self.assertIn("https://www.youtube.com/playlist?list=PLmonth", result)

    def test_within_character_limit(self) -> None:
        playlist = _FakePlaylist(date(2026, 4, 1), "PLmonth", "https://www.youtube.com/playlist?list=PLmonth")
        lineup_lines = [f"{i}. 2026-04-{i:02d} (Mon) Band{i:02d} @ Venue{i:02d}" for i in range(1, 20)]
        result = _build_monthly_thread_text(playlist, lineup_lines)
        self.assertLessEqual(len(result), THREADS_MAX_CHARS)


class TestCreateThreadPost(TestCase):
    @patch("commons.threads_utils.requests.post")
    def test_two_step_publish_returns_thread_id(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            MagicMock(json=lambda: {"id": "container123"}, raise_for_status=lambda: None),
            MagicMock(json=lambda: {"id": "thread456"}, raise_for_status=lambda: None),
        ]
        result = create_thread_post("user1", "tok", "Hello Threads")
        self.assertEqual(result, "thread456")
        self.assertEqual(mock_post.call_count, 2)

    @patch("commons.threads_utils.requests.post")
    def test_create_step_uses_text_media_type(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            MagicMock(json=lambda: {"id": "c1"}, raise_for_status=lambda: None),
            MagicMock(json=lambda: {"id": "t1"}, raise_for_status=lambda: None),
        ]
        create_thread_post("user1", "tok", "Test post")
        first_call_params = mock_post.call_args_list[0].kwargs.get("params", {})
        self.assertEqual(first_call_params.get("media_type"), "TEXT")

    @patch("commons.threads_utils.requests.post")
    def test_publish_step_sends_container_id(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = [
            MagicMock(json=lambda: {"id": "container99"}, raise_for_status=lambda: None),
            MagicMock(json=lambda: {"id": "thread99"}, raise_for_status=lambda: None),
        ]
        create_thread_post("user1", "tok", "Test")
        second_call_params = mock_post.call_args_list[1].kwargs.get("params", {})
        self.assertEqual(second_call_params.get("creation_id"), "container99")
