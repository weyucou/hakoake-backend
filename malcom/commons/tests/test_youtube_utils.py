"""Tests for upload_video_to_youtube and insert_video_at_position in youtube_utils."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import googleapiclient.errors
from django.test import TestCase

from commons.youtube_utils import get_video_durations, parse_iso8601_duration


class TestUploadVideoToYoutube(TestCase):
    @patch("commons.youtube_utils.get_authorized_youtube_client")
    @patch("commons.youtube_utils.googleapiclient.http.MediaFileUpload")
    def test_returns_video_id(self, mock_media_upload: MagicMock, mock_get_client: MagicMock) -> None:
        from commons.youtube_utils import upload_video_to_youtube

        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube
        mock_request = MagicMock()
        mock_request.next_chunk.return_value = (None, {"id": "abc123"})
        mock_youtube.videos.return_value.insert.return_value = mock_request

        video_id = upload_video_to_youtube(
            video_path=Path("/tmp/intro.mp4"),  # noqa: S108
            title="Test Video",
            description="A test",
            client_secrets_file=Path("/tmp/client_secret.json"),  # noqa: S108
        )

        self.assertEqual(video_id, "abc123")

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    @patch("commons.youtube_utils.googleapiclient.http.MediaFileUpload")
    def test_logs_progress_when_status_present(self, mock_media_upload: MagicMock, mock_get_client: MagicMock) -> None:
        from commons.youtube_utils import upload_video_to_youtube

        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube

        mock_status = MagicMock()
        mock_status.progress.return_value = 0.5

        mock_request = MagicMock()
        mock_request.next_chunk.side_effect = [
            (mock_status, None),
            (None, {"id": "xyz789"}),
        ]
        mock_youtube.videos.return_value.insert.return_value = mock_request

        video_id = upload_video_to_youtube(
            video_path=Path("/tmp/intro.mp4"),  # noqa: S108
            title="Test",
            description="desc",
            client_secrets_file=Path("/tmp/client_secret.json"),  # noqa: S108
        )

        self.assertEqual(video_id, "xyz789")

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    @patch("commons.youtube_utils.googleapiclient.http.MediaFileUpload")
    def test_uses_provided_privacy_status(self, mock_media_upload: MagicMock, mock_get_client: MagicMock) -> None:
        from commons.youtube_utils import upload_video_to_youtube

        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube
        mock_request = MagicMock()
        mock_request.next_chunk.return_value = (None, {"id": "priv1"})
        mock_youtube.videos.return_value.insert.return_value = mock_request

        upload_video_to_youtube(
            video_path=Path("/tmp/intro.mp4"),  # noqa: S108
            title="T",
            description="D",
            client_secrets_file=Path("/tmp/client_secret.json"),  # noqa: S108
            privacy_status="private",
        )

        call_kwargs = mock_youtube.videos.return_value.insert.call_args[1]
        self.assertEqual(call_kwargs["body"]["status"]["privacyStatus"], "private")


class TestInsertVideoAtPosition(TestCase):
    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_returns_true_on_success(self, mock_get_client: MagicMock) -> None:
        from commons.youtube_utils import insert_video_at_position

        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube

        result = insert_video_at_position("PL123", "vid456", 0, Path("/tmp/client_secret.json"))  # noqa: S108

        self.assertTrue(result)
        mock_youtube.playlistItems.return_value.insert.assert_called_once()
        call_body = mock_youtube.playlistItems.return_value.insert.call_args[1]["body"]
        self.assertEqual(call_body["snippet"]["position"], 0)
        self.assertEqual(call_body["snippet"]["playlistId"], "PL123")
        self.assertEqual(call_body["snippet"]["resourceId"]["videoId"], "vid456")

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_returns_false_on_http_error(self, mock_get_client: MagicMock) -> None:
        import googleapiclient.errors

        from commons.youtube_utils import insert_video_at_position

        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube

        mock_resp = MagicMock()
        mock_resp.status = 403
        mock_resp.reason = "Forbidden"
        mock_youtube.playlistItems.return_value.insert.return_value.execute.side_effect = (
            googleapiclient.errors.HttpError(mock_resp, b"Forbidden")
        )

        result = insert_video_at_position("PL123", "vid456", 0, Path("/tmp/client_secret.json"))  # noqa: S108

        self.assertFalse(result)

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_inserts_at_specified_position(self, mock_get_client: MagicMock) -> None:
        from commons.youtube_utils import insert_video_at_position

        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube

        insert_video_at_position("PL999", "vidABC", 3, Path("/tmp/client_secret.json"))  # noqa: S108

        call_body = mock_youtube.playlistItems.return_value.insert.call_args[1]["body"]
        self.assertEqual(call_body["snippet"]["position"], 3)


class TestParseIso8601Duration(TestCase):
    def test_minutes_and_seconds(self) -> None:
        self.assertEqual(parse_iso8601_duration("PT4M37S"), 4 * 60 + 37)

    def test_hours_minutes_seconds(self) -> None:
        self.assertEqual(parse_iso8601_duration("PT1H2M3S"), 3600 + 120 + 3)

    def test_seconds_only(self) -> None:
        self.assertEqual(parse_iso8601_duration("PT30S"), 30)

    def test_unparseable_returns_zero(self) -> None:
        self.assertEqual(parse_iso8601_duration("LIVE"), 0)
        self.assertEqual(parse_iso8601_duration(""), 0)
        self.assertEqual(parse_iso8601_duration("not a duration"), 0)


class TestGetVideoDurations(TestCase):
    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_empty_input_returns_empty_dict_without_api_call(self, mock_get_client: MagicMock) -> None:
        result = get_video_durations([], Path("/tmp/client_secret.json"))  # noqa: S108

        self.assertEqual(result, {})
        mock_get_client.assert_not_called()

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_returns_durations_for_listed_videos(self, mock_get_client: MagicMock) -> None:
        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "vid_short", "contentDetails": {"duration": "PT3M22S"}},
                {"id": "vid_long", "contentDetails": {"duration": "PT41M12S"}},
            ]
        }

        result = get_video_durations(
            ["vid_short", "vid_long"],
            Path("/tmp/client_secret.json"),  # noqa: S108
        )

        self.assertEqual(result, {"vid_short": 3 * 60 + 22, "vid_long": 41 * 60 + 12})
        mock_youtube.videos.return_value.list.assert_called_once_with(part="contentDetails", id="vid_short,vid_long")

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_unavailable_video_omitted_from_result(self, mock_get_client: MagicMock) -> None:
        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube
        # Only one of two requested IDs comes back (the other is deleted/private)
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "vid_alive", "contentDetails": {"duration": "PT2M0S"}},
            ]
        }

        result = get_video_durations(
            ["vid_alive", "vid_dead"],
            Path("/tmp/client_secret.json"),  # noqa: S108
        )

        self.assertEqual(result, {"vid_alive": 120})
        self.assertNotIn("vid_dead", result)

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_batches_in_groups_of_50(self, mock_get_client: MagicMock) -> None:
        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube
        # Return one item per requested ID per call
        mock_youtube.videos.return_value.list.return_value.execute.side_effect = [
            {"items": [{"id": f"vid{i}", "contentDetails": {"duration": "PT1M0S"}} for i in range(50)]},
            {"items": [{"id": f"vid{i}", "contentDetails": {"duration": "PT1M0S"}} for i in range(50, 75)]},
        ]

        video_ids = [f"vid{i}" for i in range(75)]
        result = get_video_durations(video_ids, Path("/tmp/client_secret.json"))  # noqa: S108

        self.assertEqual(len(result), 75)
        self.assertEqual(mock_youtube.videos.return_value.list.call_count, 2)

    @patch("commons.youtube_utils.get_authorized_youtube_client")
    def test_http_error_skips_batch_returns_partial(self, mock_get_client: MagicMock) -> None:
        mock_youtube = MagicMock()
        mock_get_client.return_value = mock_youtube

        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.reason = "Server Error"
        mock_youtube.videos.return_value.list.return_value.execute.side_effect = googleapiclient.errors.HttpError(
            mock_resp, b"Server Error"
        )

        result = get_video_durations(
            ["vid_a", "vid_b"],
            Path("/tmp/client_secret.json"),  # noqa: S108
        )

        self.assertEqual(result, {})
