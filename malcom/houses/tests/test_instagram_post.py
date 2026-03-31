"""Tests for Instagram carousel posting — caption builder, image generator, API flow."""

from __future__ import annotations

import io
from datetime import date
from unittest.mock import MagicMock, patch

from commons.instagram_images import generate_playlist_cover
from commons.instagram_post import build_caption, post_carousel
from django.test import TestCase

# ---------------------------------------------------------------------------
# Caption tests
# ---------------------------------------------------------------------------


class TestBuildCaption(TestCase):
    def test_includes_description(self) -> None:
        caption = build_caption("My description", "https://youtube.com/playlist?list=ABC")
        self.assertIn("My description", caption)

    def test_includes_playlist_url(self) -> None:
        url = "https://youtube.com/playlist?list=ABC"
        caption = build_caption("desc", url)
        self.assertIn(url, caption)

    def test_includes_hashtags(self) -> None:
        caption = build_caption("desc", "https://yt.com", extra_hashtags=("hakoake", "tokyo"))
        self.assertIn("#hakoake", caption)
        self.assertIn("#tokyo", caption)

    def test_truncated_to_2200_chars(self) -> None:
        long_desc = "x" * 3000
        caption = build_caption(long_desc, "https://yt.com")
        self.assertLessEqual(len(caption), 2200)


# ---------------------------------------------------------------------------
# Image generation tests
# ---------------------------------------------------------------------------


class TestGeneratePlaylistCover(TestCase):
    def test_returns_jpeg_bytes(self) -> None:
        entries = [(1, "AKIARIM"), (2, "Lailah"), (3, "Carabina")]
        result = generate_playlist_cover("Test Playlist", "Week of 2026-03-30", entries)
        self.assertIsInstance(result, bytes)
        # JPEG magic bytes
        self.assertEqual(result[:2], b"\xff\xd8")

    def test_handles_empty_entries(self) -> None:
        result = generate_playlist_cover("Test", "Week of 2026-03-30", [])
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_handles_more_than_10_entries(self) -> None:
        entries = [(i, f"Performer {i}") for i in range(1, 15)]
        result = generate_playlist_cover("Test", "Week of 2026-03-30", entries)
        self.assertIsInstance(result, bytes)


# ---------------------------------------------------------------------------
# API flow tests
# ---------------------------------------------------------------------------


class TestPostCarousel(TestCase):
    def _make_images(self, n: int) -> list[tuple[bytes, str]]:
        """Create n minimal JPEG images."""
        from PIL import Image

        images = []
        for i in range(n):
            buf = io.BytesIO()
            Image.new("RGB", (100, 100), color=(i * 20, 0, 0)).save(buf, format="JPEG")
            images.append((buf.getvalue(), f"img_{i}.jpg"))
        return images

    @patch("commons.instagram_post.publish_media", return_value="post_123")
    @patch("commons.instagram_post.create_carousel_container", return_value="container_99")
    @patch("commons.instagram_post.create_carousel_item", side_effect=["child_1", "child_2"])
    @patch("commons.instagram_post.upload_image", side_effect=["handle_1", "handle_2"])
    def test_full_flow_returns_post_id(
        self,
        mock_upload: MagicMock,
        mock_item: MagicMock,
        mock_container: MagicMock,
        mock_publish: MagicMock,
    ) -> None:
        images = self._make_images(2)
        post_id = post_carousel("user_id", "token", images, "caption")
        self.assertEqual(post_id, "post_123")
        self.assertEqual(mock_upload.call_count, 2)
        self.assertEqual(mock_item.call_count, 2)
        mock_container.assert_called_once_with("user_id", "token", ["child_1", "child_2"], "caption")
        mock_publish.assert_called_once_with("user_id", "token", "container_99")

    def test_raises_on_too_few_images(self) -> None:
        with self.assertRaises(ValueError):
            post_carousel("u", "t", self._make_images(1), "caption")

    def test_raises_on_too_many_images(self) -> None:
        with self.assertRaises(ValueError):
            post_carousel("u", "t", self._make_images(11), "caption")


# ---------------------------------------------------------------------------
# Management command dry-run test
# ---------------------------------------------------------------------------


class TestPostWeeklyPlaylistInstagramCommand(TestCase):
    def setUp(self) -> None:
        from performers.models import Performer, PerformerSong

        from houses.models import WeeklyPlaylist, WeeklyPlaylistEntry

        # Performer
        self.performer = Performer(name="TestBand", name_kana="テスト", name_romaji="TestBand")
        self.performer._skip_image_fetch = True  # noqa: SLF001
        self.performer.save()

        # Song
        self.song = PerformerSong.objects.create(
            performer=self.performer,
            title="Test Song",
            youtube_video_id="abc123",
            youtube_url="https://www.youtube.com/watch?v=abc123",
            youtube_view_count=1000,
            youtube_duration_seconds=200,
        )

        # Playlist
        self.playlist = WeeklyPlaylist.objects.create(
            date=date(2026, 3, 30),
            youtube_playlist_id="PLtest123",
            youtube_playlist_url="https://www.youtube.com/playlist?list=PLtest123",
        )
        WeeklyPlaylistEntry.objects.create(playlist=self.playlist, song=self.song, position=1)

    def test_dry_run_does_not_post(self) -> None:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with patch("commons.instagram_post.post_carousel") as mock_post:
            call_command("post_weekly_playlist_instagram", str(self.playlist.id), "--dry-run", stdout=out)
        mock_post.assert_not_called()
        self.assertIn("Dry run complete", out.getvalue())

    def test_dry_run_output_contains_caption(self) -> None:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("post_weekly_playlist_instagram", str(self.playlist.id), "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("CAPTION", output)
        self.assertIn("PLtest123", output)
