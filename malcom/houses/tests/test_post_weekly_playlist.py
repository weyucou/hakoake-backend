"""Tests for the post_weekly_playlist management command."""

from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from performers.models import Performer, PerformerSong

from houses.models import WeeklyPlaylist, WeeklyPlaylistEntry


def _make_performer(name: str = "TestBand") -> Performer:
    performer = Performer(name=name, name_kana="テスト", name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    return performer


def _make_song(performer: Performer, title: str = "Test Song", video_id: str = "abc123") -> PerformerSong:
    return PerformerSong.objects.create(
        performer=performer,
        title=title,
        youtube_video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        youtube_view_count=1000,
        youtube_duration_seconds=200,
    )


class TestPostWeeklyPlaylistCommand(TestCase):
    def setUp(self) -> None:
        self.performer = _make_performer()
        self.song = _make_song(self.performer)
        self.playlist = WeeklyPlaylist.objects.create(
            date=date(2026, 3, 30),
            youtube_playlist_id="PLtest123",
            youtube_playlist_url="https://www.youtube.com/playlist?list=PLtest123",
        )
        WeeklyPlaylistEntry.objects.create(playlist=self.playlist, song=self.song, position=1)

    def test_dry_run_does_not_post(self) -> None:
        out = StringIO()
        with patch("commons.instagram_post.post_carousel") as mock_post:
            call_command("post_weekly_playlist", "--dry-run", stdout=out)
        mock_post.assert_not_called()
        self.assertIn("Dry run complete", out.getvalue())

    def test_dry_run_with_explicit_playlist_id(self) -> None:
        out = StringIO()
        with patch("commons.instagram_post.post_carousel") as mock_post:
            call_command("post_weekly_playlist", f"--playlist-id={self.playlist.id}", "--dry-run", stdout=out)
        mock_post.assert_not_called()
        output = out.getvalue()
        self.assertIn("Dry run complete", output)
        self.assertIn(str(self.playlist.id), output)

    def test_dry_run_output_contains_caption(self) -> None:
        out = StringIO()
        call_command("post_weekly_playlist", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("CAPTION", output)
        self.assertIn("PLtest123", output)

    def test_dry_run_generates_cover_and_slides(self) -> None:
        out = StringIO()
        call_command("post_weekly_playlist", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("cover image", output)
        self.assertIn("TestBand", output)
        self.assertIn("Total slides", output)

    def test_invalid_playlist_id_exits_gracefully(self) -> None:
        err = StringIO()
        call_command("post_weekly_playlist", "--playlist-id=99999", "--dry-run", stderr=err)
        self.assertIn("not found", err.getvalue())

    def test_truncates_to_max_when_entries_exceed_limit(self) -> None:
        # Add enough entries to exceed the 4-performer carousel cap
        for i in range(2, 7):
            song = _make_song(self.performer, title=f"Extra Song {i}", video_id=f"extra{i}")
            WeeklyPlaylistEntry.objects.create(playlist=self.playlist, song=song, position=i)

        out = StringIO()
        with self.assertLogs("houses.management.commands.post_weekly_playlist", level="WARNING") as cm:
            call_command("post_weekly_playlist", "--dry-run", stdout=out)
        self.assertTrue(any("truncating" in msg for msg in cm.output))

    def test_uses_latest_playlist_when_no_id_given(self) -> None:
        newer_playlist = WeeklyPlaylist.objects.create(
            date=date(2026, 4, 6),
            youtube_playlist_id="PLnewer",
            youtube_playlist_url="https://www.youtube.com/playlist?list=PLnewer",
        )
        song2 = _make_song(self.performer, title="Newer Song", video_id="newer123")
        WeeklyPlaylistEntry.objects.create(playlist=newer_playlist, song=song2, position=1)

        out = StringIO()
        call_command("post_weekly_playlist", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn(str(newer_playlist.id), output)
