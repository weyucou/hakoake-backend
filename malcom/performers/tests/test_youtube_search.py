"""Tests for YouTube search and channel validation."""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase

from performers.models import Performer, PerformerSocialLink
from performers.youtube_search import YouTubeSearcher, search_and_create_performer_songs


def _create_performer(name: str) -> Performer:
    """Create a performer with image fetch skipped."""
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    return performer


class TestChannelMatchesPerformer(TestCase):
    """Tests for YouTubeSearcher.channel_matches_performer()."""

    def setUp(self) -> None:
        self.searcher = YouTubeSearcher()

    def test_channel_matches_performer_by_name(self) -> None:
        result = self.searcher.channel_matches_performer(
            performer_name="RAN",
            channel_name="RAN Official",
            channel_id="UC123",
        )
        self.assertTrue(result)

    def test_channel_matches_performer_by_description(self) -> None:
        with patch.object(self.searcher, "_fetch_channel_description", return_value="Official channel of RAN band"):
            result = self.searcher.channel_matches_performer(
                performer_name="RAN",
                channel_name="Some Label Channel",
                channel_id="UC123",
            )
        self.assertTrue(result)

    def test_channel_does_not_match_performer(self) -> None:
        with patch.object(self.searcher, "_fetch_channel_description", return_value="Music compilation channel"):
            result = self.searcher.channel_matches_performer(
                performer_name="RAN",
                channel_name="TopMusic",
                channel_id="UC123",
            )
        self.assertFalse(result)

    def test_channel_matches_with_japanese_normalization(self) -> None:
        """NFKC and katakana normalization allows matching Japanese names."""
        result = self.searcher.channel_matches_performer(
            performer_name="バンド",
            channel_name="ばんど公式",
            channel_id="UC123",
        )
        self.assertTrue(result)

    def test_no_channel_id_skips_description_fetch(self) -> None:
        with patch.object(self.searcher, "_fetch_channel_description") as mock_fetch:
            result = self.searcher.channel_matches_performer(
                performer_name="RAN",
                channel_name="TopMusic",
                channel_id="",
            )
        self.assertFalse(result)
        mock_fetch.assert_not_called()


class TestFetchChannelDescription(TestCase):
    """Tests for YouTubeSearcher._fetch_channel_description()."""

    def setUp(self) -> None:
        self.searcher = YouTubeSearcher()

    def test_fetch_channel_description_success(self) -> None:
        yt_data = {
            "metadata": {
                "channelMetadataRenderer": {
                    "description": "We are RAN, a rock band from Tokyo.",
                }
            }
        }
        html = f"<html>var ytInitialData = {json.dumps(yt_data)};</script></html>"
        mock_response = MagicMock(status_code=200, text=html)

        with patch.object(self.searcher.session, "get", return_value=mock_response):
            result = self.searcher._fetch_channel_description("UC123")  # noqa: SLF001

        self.assertEqual(result, "We are RAN, a rock band from Tokyo.")

    def test_fetch_channel_description_network_error(self) -> None:
        with patch.object(self.searcher.session, "get", side_effect=ConnectionError("timeout")):
            result = self.searcher._fetch_channel_description("UC123")  # noqa: SLF001

        self.assertEqual(result, "")

    def test_fetch_channel_description_missing_metadata(self) -> None:
        yt_data = {"contents": {}}
        html = f"<html>var ytInitialData = {json.dumps(yt_data)};</script></html>"
        mock_response = MagicMock(status_code=200, text=html)

        with patch.object(self.searcher.session, "get", return_value=mock_response):
            result = self.searcher._fetch_channel_description("UC123")  # noqa: SLF001

        self.assertEqual(result, "")


class TestSearchAndCreatePerformerSongsChannelValidation(TestCase):
    """Integration tests for channel validation in search_and_create_performer_songs()."""

    def _make_video_data(self, channel_name: str = "RAN Official", channel_id: str = "UC123") -> list[dict]:
        return [
            {
                "video_id": "abc123",
                "title": "RAN - Song Title",
                "channel_name": channel_name,
                "channel_id": channel_id,
                "youtube_url": "https://www.youtube.com/watch?v=abc123",
                "view_count": 1000,
                "duration_seconds": 240,
            },
        ]

    @patch("performers.youtube_search.YouTubeSearcher.search_most_popular_videos")
    @patch("performers.youtube_search.YouTubeSearcher.channel_matches_performer")
    def test_social_link_not_created_when_channel_does_not_match(
        self, mock_matches: MagicMock, mock_search: MagicMock
    ) -> None:
        performer = _create_performer("RAN")
        mock_search.return_value = self._make_video_data(channel_name="TopMusic Label")
        mock_matches.return_value = False

        songs = search_and_create_performer_songs(performer)

        self.assertEqual(len(songs), 1)
        self.assertFalse(PerformerSocialLink.objects.filter(performer=performer, platform="youtube").exists())

    @patch("performers.youtube_search.YouTubeSearcher.search_most_popular_videos")
    @patch("performers.youtube_search.YouTubeSearcher.channel_matches_performer")
    def test_social_link_created_when_channel_matches(self, mock_matches: MagicMock, mock_search: MagicMock) -> None:
        performer = _create_performer("RAN")
        mock_search.return_value = self._make_video_data()
        mock_matches.return_value = True

        songs = search_and_create_performer_songs(performer)

        self.assertEqual(len(songs), 1)
        link = PerformerSocialLink.objects.get(performer=performer, platform="youtube")
        self.assertEqual(link.platform_id, "UC123")
        self.assertEqual(link.url, "https://www.youtube.com/channel/UC123")

    @patch("performers.youtube_search.YouTubeSearcher.search_most_popular_videos")
    @patch("performers.youtube_search.YouTubeSearcher.channel_matches_performer")
    def test_second_video_channel_checked_when_first_does_not_match(
        self, mock_matches: MagicMock, mock_search: MagicMock
    ) -> None:
        """When the first video's channel doesn't match, subsequent videos are still checked."""
        performer = _create_performer("RAN")
        mock_search.return_value = [
            {
                "video_id": "abc123",
                "title": "RAN - Song 1",
                "channel_name": "TopMusic Label",
                "channel_id": "UC_LABEL",
                "youtube_url": "https://www.youtube.com/watch?v=abc123",
                "view_count": 5000,
                "duration_seconds": 200,
            },
            {
                "video_id": "def456",
                "title": "RAN - Song 2",
                "channel_name": "RAN Official",
                "channel_id": "UC_RAN",
                "youtube_url": "https://www.youtube.com/watch?v=def456",
                "view_count": 3000,
                "duration_seconds": 180,
            },
        ]
        mock_matches.side_effect = [False, True]

        songs = search_and_create_performer_songs(performer)

        self.assertEqual(len(songs), 2)
        link = PerformerSocialLink.objects.get(performer=performer, platform="youtube")
        self.assertEqual(link.platform_id, "UC_RAN")
