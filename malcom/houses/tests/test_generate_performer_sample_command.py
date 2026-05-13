"""Tests for the generate_performer_sample management command and download helper."""

from __future__ import annotations

from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from performers.models import Performer, PerformerSong

from houses.functions import download_performer_song_audio
from houses.models import MonthlyPlaylist, MonthlyPlaylistEntry, WeeklyPlaylist, WeeklyPlaylistEntry


def _make_performer(name: str = "TestBand") -> Performer:
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    return performer


def _make_song(
    performer: Performer,
    title: str = "Test Song",
    video_id: str = "abc123",
    youtube_url: str = "",
) -> PerformerSong:
    return PerformerSong.objects.create(
        performer=performer,
        title=title,
        youtube_video_id=video_id,
        youtube_url=youtube_url or f"https://www.youtube.com/watch?v={video_id}",
        youtube_view_count=1000,
        youtube_duration_seconds=200,
    )


class TestDownloadPerformerSongAudio(TestCase):
    def setUp(self) -> None:
        self.performer = _make_performer()
        self.song_with_url = _make_song(self.performer, video_id="vidABC")
        self.song_without_url = PerformerSong.objects.create(
            performer=self.performer,
            title="No URL Song",
            youtube_url="",
        )

    def test_returns_none_when_no_youtube_url(self) -> None:
        result = download_performer_song_audio(self.song_without_url)
        self.assertIsNone(result)

    def test_returns_cached_path_when_file_exists_and_not_forced(self) -> None:
        with patch("houses.functions.Path.exists", return_value=True):
            # Patch at the sample dir / song_id.mp3 level
            result = download_performer_song_audio(self.song_with_url, force=False)
        # When file exists, should return the path without calling yt_dlp
        # (yt_dlp would be called if it proceeded past the cache check)
        self.assertIsNotNone(result)

    def test_calls_yt_dlp_when_file_missing(self) -> None:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with (
            patch("houses.functions.Path.exists", return_value=False),
            patch("yt_dlp.YoutubeDL", return_value=mock_ydl) as mock_ydl_cls,
        ):
            download_performer_song_audio(self.song_with_url)

        mock_ydl_cls.assert_called_once()
        mock_ydl.download.assert_called_once_with([self.song_with_url.youtube_url])

    def test_returns_none_on_download_failure(self) -> None:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.download.side_effect = Exception("network error")

        with (
            patch("houses.functions.Path.exists", return_value=False),
            patch("yt_dlp.YoutubeDL", return_value=mock_ydl),
        ):
            result = download_performer_song_audio(self.song_with_url)

        self.assertIsNone(result)

    def test_force_flag_skips_cache_check(self) -> None:
        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with (
            # File "exists" but force=True should still call download
            patch("houses.functions.Path.exists", return_value=True),
            patch("yt_dlp.YoutubeDL", return_value=mock_ydl) as mock_ydl_cls,
        ):
            download_performer_song_audio(self.song_with_url, force=True)

        mock_ydl_cls.assert_called_once()


class TestGeneratePerformerSampleCommand(TestCase):
    def setUp(self) -> None:
        self.performer1 = _make_performer("BandAlpha")
        self.performer2 = _make_performer("BandBeta")
        self.song1 = _make_song(self.performer1, video_id="vid001")
        self.song2 = _make_song(self.performer2, video_id="vid002")
        self.song_no_url = PerformerSong.objects.create(
            performer=self.performer1,
            title="Silent Track",
            youtube_url="",
        )

        self.weekly_playlist = WeeklyPlaylist.objects.create(
            date=date(2026, 3, 30),
            youtube_playlist_id="PLweek1",
            youtube_playlist_url="https://www.youtube.com/playlist?list=PLweek1",
        )
        WeeklyPlaylistEntry.objects.create(playlist=self.weekly_playlist, song=self.song1, position=1)
        WeeklyPlaylistEntry.objects.create(playlist=self.weekly_playlist, song=self.song2, position=2)

        self.monthly_playlist = MonthlyPlaylist.objects.create(
            date=date(2026, 3, 1),
            youtube_playlist_id="PLmonth1",
            youtube_playlist_url="https://www.youtube.com/playlist?list=PLmonth1",
        )
        MonthlyPlaylistEntry.objects.create(playlist=self.monthly_playlist, song=self.song1, position=1)

    def _patch_download(self, return_path: Path | None = None) -> MagicMock:
        return patch(
            "houses.management.commands.generate_performer_sample.download_performer_song_audio",
            return_value=return_path,
        )

    def test_weekly_playlist_downloads_all_songs(self) -> None:
        fake_path = Path("/tmp/fake_audio.mp3")  # noqa: S108
        out = StringIO()
        with (
            self._patch_download(return_path=fake_path) as mock_dl,
            patch("houses.management.commands.generate_performer_sample.Path.exists", return_value=False),
        ):
            call_command(
                "generate_performer_sample",
                f"--weekly-playlist-id={self.weekly_playlist.id}",
                stdout=out,
            )

        self.assertEqual(mock_dl.call_count, 2)
        called_songs = {call.args[0].id for call in mock_dl.call_args_list}
        self.assertIn(self.song1.id, called_songs)
        self.assertIn(self.song2.id, called_songs)

    def test_monthly_playlist_downloads_songs(self) -> None:
        fake_path = Path("/tmp/fake_audio.mp3")  # noqa: S108
        out = StringIO()
        with (
            self._patch_download(return_path=fake_path) as mock_dl,
            patch("houses.management.commands.generate_performer_sample.Path.exists", return_value=False),
        ):
            call_command(
                "generate_performer_sample",
                f"--monthly-playlist-id={self.monthly_playlist.id}",
                stdout=out,
            )

        self.assertEqual(mock_dl.call_count, 1)
        self.assertEqual(mock_dl.call_args.args[0].id, self.song1.id)

    def test_performer_id_filters_to_single_performer_in_weekly_playlist(self) -> None:
        fake_path = Path("/tmp/fake_audio.mp3")  # noqa: S108
        out = StringIO()
        with (
            self._patch_download(return_path=fake_path) as mock_dl,
            patch("houses.management.commands.generate_performer_sample.Path.exists", return_value=False),
        ):
            call_command(
                "generate_performer_sample",
                f"--weekly-playlist-id={self.weekly_playlist.id}",
                f"--performer-id={self.performer1.id}",
                stdout=out,
            )

        # Only performer1's song (song1) should be downloaded; performer2 (song2) is excluded
        self.assertEqual(mock_dl.call_count, 1)
        self.assertEqual(mock_dl.call_args.args[0].id, self.song1.id)

    def test_performer_id_filters_to_single_performer_in_monthly_playlist(self) -> None:
        # Add performer2's song to the monthly playlist for this test
        from houses.models import MonthlyPlaylistEntry  # noqa: PLC0415

        MonthlyPlaylistEntry.objects.create(playlist=self.monthly_playlist, song=self.song2, position=2)

        fake_path = Path("/tmp/fake_audio.mp3")  # noqa: S108
        out = StringIO()
        with (
            self._patch_download(return_path=fake_path) as mock_dl,
            patch("houses.management.commands.generate_performer_sample.Path.exists", return_value=False),
        ):
            call_command(
                "generate_performer_sample",
                f"--monthly-playlist-id={self.monthly_playlist.id}",
                f"--performer-id={self.performer2.id}",
                stdout=out,
            )

        self.assertEqual(mock_dl.call_count, 1)
        self.assertEqual(mock_dl.call_args.args[0].id, self.song2.id)

    def test_missing_weekly_playlist_id_writes_error(self) -> None:
        err = StringIO()
        call_command(
            "generate_performer_sample",
            "--weekly-playlist-id=99999",
            stderr=err,
        )
        self.assertIn("not found", err.getvalue())

    def test_missing_monthly_playlist_id_writes_error(self) -> None:
        err = StringIO()
        call_command(
            "generate_performer_sample",
            "--monthly-playlist-id=99999",
            stderr=err,
        )
        self.assertIn("not found", err.getvalue())

    def test_performer_id_not_in_playlist_writes_error(self) -> None:
        performer3 = _make_performer("BandGamma")
        err = StringIO()
        call_command(
            "generate_performer_sample",
            f"--weekly-playlist-id={self.weekly_playlist.id}",
            f"--performer-id={performer3.id}",
            stderr=err,
        )
        self.assertIn("No songs found", err.getvalue())

    def test_failed_download_counted_in_output(self) -> None:
        out = StringIO()
        with (
            self._patch_download(return_path=None),
            patch("houses.management.commands.generate_performer_sample.Path.exists", return_value=False),
        ):
            call_command(
                "generate_performer_sample",
                f"--weekly-playlist-id={self.weekly_playlist.id}",
                stdout=out,
            )

        self.assertIn("failed: 2", out.getvalue())
