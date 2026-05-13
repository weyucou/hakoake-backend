"""Tests for the generate_weekly_playlist_video management command."""

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from houses.models import WeeklyPlaylist


class TestGenerateWeeklyPlaylistVideoCommand(TestCase):
    def setUp(self) -> None:
        self.playlist = WeeklyPlaylist.objects.create(
            date=date(2026, 3, 30),
            youtube_playlist_id="PLtest123",
            youtube_playlist_url="https://www.youtube.com/playlist?list=PLtest123",
        )

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_uploads_and_inserts_at_position_zero_by_default(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        with (
            tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video,
            tempfile.NamedTemporaryFile(suffix=".json") as tmp_secret,
        ):
            mock_gen.return_value = Path(tmp_video.name)
            mock_upload.return_value = "uploaded_vid_id"
            mock_insert.return_value = True

            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                secrets_file=tmp_secret.name,
            )

        mock_upload.assert_called_once()
        upload_args = mock_upload.call_args[0]
        self.assertEqual(upload_args[0], Path(tmp_video.name))
        self.assertIn("2026-03-30", upload_args[1])  # title contains week date

        mock_insert.assert_called_once()
        insert_args = mock_insert.call_args[0]
        self.assertEqual(insert_args[0], "PLtest123")  # playlist_id
        self.assertEqual(insert_args[1], "uploaded_vid_id")  # video_id
        self.assertEqual(insert_args[2], 0)  # position = first

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_skip_update_playlist_bypasses_upload_and_insert(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video:
            mock_gen.return_value = Path(tmp_video.name)
            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                skip_update_playlist=True,
            )

        mock_upload.assert_not_called()
        mock_insert.assert_not_called()

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_skips_upload_when_secrets_file_missing(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video:
            mock_gen.return_value = Path(tmp_video.name)
            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                secrets_file="/nonexistent/client_secret.json",
            )

        mock_upload.assert_not_called()
        mock_insert.assert_not_called()

    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_error_when_playlist_not_found(self, mock_gen: MagicMock) -> None:
        from io import StringIO

        err = StringIO()
        call_command("generate_weekly_playlist_video", "99999", stderr=err)
        self.assertIn("not found", err.getvalue())
        mock_gen.assert_not_called()

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_skips_insert_when_upload_fails(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        with (
            tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video,
            tempfile.NamedTemporaryFile(suffix=".json") as tmp_secret,
        ):
            mock_gen.return_value = Path(tmp_video.name)
            mock_upload.side_effect = Exception("quota exceeded")
            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                secrets_file=tmp_secret.name,
            )

        mock_insert.assert_not_called()

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_skips_when_upload_and_insert_already_recorded(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        """AC: already-uploaded-and-inserted playlist is a no-op."""
        self.playlist.intro_youtube_video_id = "existing_vid"
        self.playlist.intro_video_inserted_datetime = timezone.now()
        self.playlist.save()

        with tempfile.NamedTemporaryFile(suffix=".json") as tmp_secret:
            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                secrets_file=tmp_secret.name,
            )

        mock_gen.assert_not_called()
        mock_upload.assert_not_called()
        mock_insert.assert_not_called()

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_insert_only_when_upload_done_but_insert_missing(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        """AC: only insert is retried when upload already persisted."""
        self.playlist.intro_youtube_video_id = "persisted_vid"
        self.playlist.save()
        mock_insert.return_value = True

        with tempfile.NamedTemporaryFile(suffix=".json") as tmp_secret:
            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                secrets_file=tmp_secret.name,
            )

        mock_gen.assert_not_called()
        mock_upload.assert_not_called()
        mock_insert.assert_called_once()
        insert_args = mock_insert.call_args[0]
        self.assertEqual(insert_args[0], "PLtest123")
        self.assertEqual(insert_args[1], "persisted_vid")
        self.assertEqual(insert_args[2], 0)

        self.playlist.refresh_from_db()
        self.assertIsNotNone(self.playlist.intro_video_inserted_datetime)

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_force_reuploads_and_clears_prior_state(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        """AC: --force bypasses guards and clears prior intro fields before re-render."""
        self.playlist.intro_youtube_video_id = "old_vid"
        self.playlist.intro_video_inserted_datetime = timezone.now()
        self.playlist.save()

        with (
            tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video,
            tempfile.NamedTemporaryFile(suffix=".json") as tmp_secret,
        ):
            mock_gen.return_value = Path(tmp_video.name)
            mock_upload.return_value = "new_vid"
            mock_insert.return_value = True

            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                secrets_file=tmp_secret.name,
                force=True,
            )

        mock_gen.assert_called_once()
        mock_upload.assert_called_once()
        mock_insert.assert_called_once()

        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.intro_youtube_video_id, "new_vid")
        self.assertIsNotNone(self.playlist.intro_video_inserted_datetime)

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video_shorts")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_format_shorts_invokes_shorts_generator_and_skips_upload(
        self,
        mock_standard_gen: MagicMock,
        mock_shorts_gen: MagicMock,
        mock_upload: MagicMock,
        mock_insert: MagicMock,
    ) -> None:
        """AC: --format shorts routes to the shorts generator and never uploads/inserts."""
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video:
            mock_shorts_gen.return_value = Path(tmp_video.name)
            call_command(
                "generate_weekly_playlist_video",
                str(self.playlist.id),
                format="shorts",
            )

        mock_shorts_gen.assert_called_once_with(self.playlist)
        mock_standard_gen.assert_not_called()
        mock_upload.assert_not_called()
        mock_insert.assert_not_called()

        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.intro_youtube_video_id, "")
        self.assertIsNone(self.playlist.intro_video_inserted_datetime)

    @patch("houses.management.commands.generate_weekly_playlist_video.insert_video_at_position")
    @patch("houses.management.commands.generate_weekly_playlist_video.upload_video_to_youtube")
    @patch("houses.management.commands.generate_weekly_playlist_video.generate_weekly_playlist_video")
    def test_intro_video_id_persisted_before_insert(
        self, mock_gen: MagicMock, mock_upload: MagicMock, mock_insert: MagicMock
    ) -> None:
        """AC: intro_youtube_video_id is persisted immediately after upload returns.

        Simulate an insert failure (via exception) and assert the id is still
        saved — proving the save happened before insert was attempted.
        """
        captured: dict[str, str | None] = {"id_at_insert_time": None}

        def _check_persisted(*_args: object, **_kwargs: object) -> bool:
            self.playlist.refresh_from_db()
            captured["id_at_insert_time"] = self.playlist.intro_youtube_video_id
            raise RuntimeError("insert boom")

        mock_insert.side_effect = _check_persisted

        with (
            tempfile.NamedTemporaryFile(suffix=".mp4") as tmp_video,
            tempfile.NamedTemporaryFile(suffix=".json") as tmp_secret,
        ):
            mock_gen.return_value = Path(tmp_video.name)
            mock_upload.return_value = "persisted_vid"

            with self.assertRaises(RuntimeError):
                call_command(
                    "generate_weekly_playlist_video",
                    str(self.playlist.id),
                    secrets_file=tmp_secret.name,
                )

        self.assertEqual(captured["id_at_insert_time"], "persisted_vid")
        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.intro_youtube_video_id, "persisted_vid")
        self.assertIsNone(self.playlist.intro_video_inserted_datetime)
