"""Tests for YouTube search and channel validation."""

import json
from unittest.mock import MagicMock, patch

from commons.youtube_search import YouTubeSearcher, search_and_create_performer_songs
from django.test import TestCase

from performers.models import Performer, PerformerSocialLink


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

    @patch("commons.youtube_search.YouTubeSearcher.search_most_popular_videos")
    @patch("commons.youtube_search.YouTubeSearcher.channel_matches_performer")
    def test_social_link_not_created_when_channel_does_not_match(
        self, mock_matches: MagicMock, mock_search: MagicMock
    ) -> None:
        performer = _create_performer("RAN")
        mock_search.return_value = self._make_video_data(channel_name="TopMusic Label")
        mock_matches.return_value = False

        songs = search_and_create_performer_songs(performer)

        self.assertEqual(len(songs), 1)
        self.assertFalse(PerformerSocialLink.objects.filter(performer=performer, platform="youtube").exists())

    @patch("commons.youtube_search.YouTubeSearcher.search_most_popular_videos")
    @patch("commons.youtube_search.YouTubeSearcher.channel_matches_performer")
    def test_social_link_created_when_channel_matches(self, mock_matches: MagicMock, mock_search: MagicMock) -> None:
        performer = _create_performer("RAN")
        mock_search.return_value = self._make_video_data()
        mock_matches.return_value = True

        songs = search_and_create_performer_songs(performer)

        self.assertEqual(len(songs), 1)
        link = PerformerSocialLink.objects.get(performer=performer, platform="youtube")
        self.assertEqual(link.platform_id, "UC123")
        self.assertEqual(link.url, "https://www.youtube.com/channel/UC123")

    @patch("commons.youtube_search.YouTubeSearcher.search_most_popular_videos")
    @patch("commons.youtube_search.YouTubeSearcher.channel_matches_performer")
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


class TestParseDuration(TestCase):
    """Tests for YouTubeSearcher._parse_duration()."""

    def setUp(self) -> None:
        self.searcher = YouTubeSearcher()

    def test_parse_mm_ss(self) -> None:
        self.assertEqual(self.searcher._parse_duration("3:45"), 225)  # noqa: SLF001

    def test_parse_hh_mm_ss(self) -> None:
        self.assertEqual(self.searcher._parse_duration("1:23:45"), 5025)  # noqa: SLF001

    def test_parse_numeric_string(self) -> None:
        self.assertEqual(self.searcher._parse_duration("120"), 120)  # noqa: SLF001

    # English accessibility labels
    def test_parse_accessibility_label_minutes_seconds(self) -> None:
        self.assertEqual(self.searcher._parse_duration("3 minutes, 45 seconds"), 225)  # noqa: SLF001

    def test_parse_accessibility_label_hours_minutes_seconds(self) -> None:
        self.assertEqual(self.searcher._parse_duration("1 hour, 23 minutes, 45 seconds"), 5025)  # noqa: SLF001

    def test_parse_accessibility_label_minutes_only(self) -> None:
        self.assertEqual(self.searcher._parse_duration("5 minutes"), 300)  # noqa: SLF001

    # Japanese accessibility labels — confirmed format from confirm_yt_payload
    def test_parse_japanese_label_minutes_seconds(self) -> None:
        # "5 分 36 秒" = 5 minutes 36 seconds = 336 seconds
        self.assertEqual(self.searcher._parse_duration("5 分 36 秒"), 336)  # noqa: SLF001

    def test_parse_japanese_label_hours_minutes_seconds(self) -> None:
        # "1 時間 26 分 5 秒" = 1 hour 26 minutes 5 seconds = 5165 seconds
        self.assertEqual(self.searcher._parse_duration("1 時間 26 分 5 秒"), 5165)  # noqa: SLF001

    def test_parse_japanese_label_seconds_only(self) -> None:
        # "34 秒" = 34 seconds
        self.assertEqual(self.searcher._parse_duration("34 秒"), 34)  # noqa: SLF001

    def test_parse_live_returns_zero(self) -> None:
        """'LIVE' duration text must return 0 so the video is excluded by duration filters.

        Regression test for: playlist including a video over MAX duration limit.
        Root cause: fallback of 30 passed the 25–720s filter even for live streams.
        """
        self.assertEqual(self.searcher._parse_duration("LIVE"), 0)  # noqa: SLF001

    def test_parse_empty_string_returns_zero(self) -> None:
        self.assertEqual(self.searcher._parse_duration(""), 0)  # noqa: SLF001

    def test_parse_arbitrary_text_returns_zero(self) -> None:
        self.assertEqual(self.searcher._parse_duration("Premieres in 2 days"), 0)  # noqa: SLF001


class TestIsLiveVideo(TestCase):
    """Tests for YouTubeSearcher._is_live_video()."""

    def setUp(self) -> None:
        self.searcher = YouTubeSearcher()

    def test_live_via_badge_style_live_now(self) -> None:
        """Primary live detection path — confirmed from real payload: lengthText=null,
        badges=[BADGE_STYLE_TYPE_LIVE_NOW], thumbnailOverlays=[].
        """
        video = {
            "lengthText": None,
            "thumbnailOverlays": [],
            "badges": [
                {"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_LIVE_NOW", "label": "ライブ配信中"}},
                {"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_SIMPLE", "label": "CC"}},
            ],
        }
        self.assertTrue(self.searcher._is_live_video(video))  # noqa: SLF001

    def test_live_via_thumbnail_overlay_style(self) -> None:
        """Secondary live detection path via overlay style."""
        video = {"thumbnailOverlays": [{"thumbnailOverlayTimeStatusRenderer": {"style": "LIVE"}}]}
        self.assertTrue(self.searcher._is_live_video(video))  # noqa: SLF001

    def test_regular_video_not_live(self) -> None:
        """Regular recorded video — DEFAULT overlay, no live badges."""
        video = {
            "thumbnailOverlays": [{"thumbnailOverlayTimeStatusRenderer": {"style": "DEFAULT"}}],
            "badges": [],
        }
        self.assertFalse(self.searcher._is_live_video(video))  # noqa: SLF001

    def test_empty_video_not_live(self) -> None:
        self.assertFalse(self.searcher._is_live_video({}))  # noqa: SLF001


class TestSearchMostPopularVideosExcludesLive(TestCase):
    """Regression: live/unparseable-duration videos must not reach the DB."""

    def setUp(self) -> None:
        self.searcher = YouTubeSearcher()

    def _make_regular_renderer(
        self, video_id: str = "vid123", title: str = "RAN - Song", duration_text: str = "5:30"
    ) -> dict:
        """Regular recorded video — simpleText duration, DEFAULT overlay, no badges."""
        return {
            "videoRenderer": {
                "videoId": video_id,
                "title": {"runs": [{"text": title}]},
                "ownerText": {
                    "runs": [{"text": "RAN Official", "navigationEndpoint": {"browseEndpoint": {"browseId": "UC_RAN"}}}]
                },
                "lengthText": {
                    "accessibility": {"accessibilityData": {"label": "5 分 30 秒"}},
                    "simpleText": duration_text,
                },
                "viewCountText": {"simpleText": "500000 views"},
                "thumbnailOverlays": [{"thumbnailOverlayTimeStatusRenderer": {"style": "DEFAULT"}}],
                "badges": [],
            }
        }

    def _make_live_renderer(self, video_id: str = "live1", title: str = "RAN LIVE") -> dict:
        """Real live stream shape confirmed via confirm_yt_payload:
        lengthText=null, empty thumbnailOverlays, badge BADGE_STYLE_TYPE_LIVE_NOW.
        """
        return {
            "videoRenderer": {
                "videoId": video_id,
                "title": {"runs": [{"text": title}]},
                "ownerText": {
                    "runs": [{"text": "RAN Official", "navigationEndpoint": {"browseEndpoint": {"browseId": "UC_RAN"}}}]
                },
                "lengthText": None,
                "viewCountText": {"runs": [{"text": "1,234"}, {"text": " 人が視聴中"}]},
                "thumbnailOverlays": [],
                "badges": [
                    {"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_LIVE_NOW", "label": "ライブ配信中"}},
                    {"metadataBadgeRenderer": {"style": "BADGE_STYLE_TYPE_SIMPLE", "label": "CC"}},
                ],
            }
        }

    def _make_html(self, *video_renderers: dict) -> str:
        data = {
            "contents": {
                "twoColumnSearchResultsRenderer": {
                    "primaryContents": {
                        "sectionListRenderer": {
                            "contents": [{"itemSectionRenderer": {"contents": list(video_renderers)}}]
                        }
                    }
                }
            }
        }
        return f"<html>var ytInitialData = {json.dumps(data)};</script></html>"

    def test_live_stream_excluded_real_payload_shape(self) -> None:
        """Live stream with real payload shape (lengthText=null, BADGE_STYLE_TYPE_LIVE_NOW) must be excluded."""
        html = self._make_html(self._make_live_renderer())
        mock_response = MagicMock(status_code=200, text=html)
        with patch.object(self.searcher.session, "get", return_value=mock_response):
            results = self.searcher.search_most_popular_videos("RAN", min_duration_seconds=30)
        self.assertEqual(results, [])

    def test_live_stream_before_regular_does_not_abort_remaining(self) -> None:
        """A live stream early in results must not prevent subsequent regular videos from being included."""
        html = self._make_html(
            self._make_live_renderer(video_id="live1"),
            self._make_regular_renderer(video_id="reg1", duration_text="5:30"),
        )
        mock_response = MagicMock(status_code=200, text=html)
        with patch.object(self.searcher.session, "get", return_value=mock_response):
            results = self.searcher.search_most_popular_videos("RAN", min_duration_seconds=30)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["video_id"], "reg1")

    def test_regular_video_included(self) -> None:
        """A normal video with a parseable duration must be included."""
        html = self._make_html(self._make_regular_renderer(duration_text="5:30"))
        mock_response = MagicMock(status_code=200, text=html)
        with patch.object(self.searcher.session, "get", return_value=mock_response):
            results = self.searcher.search_most_popular_videos("RAN", min_duration_seconds=30)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["duration_seconds"], 330)

    def test_japanese_accessibility_label_used_when_simple_text_missing(self) -> None:
        """When simpleText is absent, the Japanese accessibility label provides the duration."""
        video_renderer = {
            "videoRenderer": {
                "videoId": "acc1",
                "title": {"runs": [{"text": "RAN - Song"}]},
                "ownerText": {
                    "runs": [{"text": "RAN Official", "navigationEndpoint": {"browseEndpoint": {"browseId": "UC_RAN"}}}]
                },
                "lengthText": {"accessibility": {"accessibilityData": {"label": "5 分 30 秒"}}},
                "viewCountText": {"simpleText": "500000 views"},
                "thumbnailOverlays": [{"thumbnailOverlayTimeStatusRenderer": {"style": "DEFAULT"}}],
                "badges": [],
            }
        }
        html = self._make_html(video_renderer)
        mock_response = MagicMock(status_code=200, text=html)
        with patch.object(self.searcher.session, "get", return_value=mock_response):
            results = self.searcher.search_most_popular_videos("RAN", min_duration_seconds=30)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["duration_seconds"], 330)
