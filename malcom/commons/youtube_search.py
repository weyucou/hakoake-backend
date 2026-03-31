import json
import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING

import requests
from performers.normalization import channel_name_matches

if TYPE_CHECKING:
    from performers.models import Performer, PerformerSong

logger = logging.getLogger(__name__)


class YouTubeSearcher:
    """Search YouTube for performer videos without requiring API key."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                )
            }
        )

    def search_most_popular_videos(
        self, performer_name: str, min_duration_seconds: int = 30, max_results: int = 3
    ) -> list[dict]:
        """
        Search for the most popular videos by a performer over the minimum duration.

        Args:
            performer_name: Name of the performer to search for
            min_duration_seconds: Minimum video duration in seconds (default 30)
            max_results: Maximum number of videos to return (default 3)

        Returns:
            List of dicts with video info, sorted by popularity (most popular first).
            Returns empty list if no relevant videos are found.
        """
        try:
            logger.debug(f"Searching YouTube for performer: {performer_name}")

            # Create search query
            search_query = f"{performer_name} music video live concert"
            search_url = f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"

            response = self.session.get(search_url, timeout=10)
            if response.status_code != requests.codes.ok:
                logger.warning(f"YouTube search failed with status {response.status_code}")
                return []

            # Parse the response to find video data
            video_data = self._extract_video_data_from_html(response.text)

            if not video_data:
                logger.debug(f"No video data found for {performer_name}")
                return []

            # Filter videos by duration and relevance to performer
            suitable_videos = []
            for video in video_data:
                if video.get("duration_seconds", 0) < min_duration_seconds:
                    continue
                if not self._is_relevant_to_performer(video, performer_name):
                    logger.debug(f"Skipping irrelevant video: {video['title']}")
                    continue
                suitable_videos.append(video)

            if not suitable_videos:
                logger.debug(f"No relevant videos found for {performer_name}")
                return []

            # Sort by view count (descending) and take the top N most popular
            suitable_videos.sort(key=lambda x: x.get("view_count", 0), reverse=True)
            top_videos = suitable_videos[:max_results]

            logger.info(f"Found {len(top_videos)} relevant videos for {performer_name}")
            for i, video in enumerate(top_videos):
                logger.debug(f"  #{i + 1}: {video['title']} ({video['view_count']} views)")

        except Exception:  # noqa: BLE001
            logger.exception(f"Error searching YouTube for {performer_name}")
            return []
        else:
            return top_videos

    def _is_relevant_to_performer(self, video: dict, performer_name: str) -> bool:
        """
        Check if a video is likely related to the performer.

        Validates that the performer name appears in the channel name, or
        prominently in the video title (at the start, or as part of
        "Artist - Song" format) to avoid selecting unrelated videos.

        Args:
            video: Video data dict with 'title' and 'channel_name' keys
            performer_name: Name of the performer to match

        Returns:
            True if the video appears to be related to the performer
        """
        # Normalize performer name for comparison
        performer_lower = performer_name.lower().strip()
        title_lower = video.get("title", "").lower()
        channel_lower = video.get("channel_name", "").lower()

        # Best match: performer name in channel name (most reliable indicator)
        if performer_lower in channel_lower:
            return True

        # Check if title starts with performer name (common format: "Artist - Song")
        if title_lower.startswith(performer_lower):
            return True

        # Check for "Artist - Song" or "Artist「Song」" format patterns
        # Match: "ArtistName - ", "ArtistName 「", "ArtistName『", "ArtistName【"
        artist_prefix_pattern = rf"^{re.escape(performer_lower)}\s*[-「『【\[]"
        if re.match(artist_prefix_pattern, title_lower):
            return True

        # Check for "[Artist]" or "(Artist)" patterns often used in titles
        bracketed_pattern = rf"[\[\(【「『]{re.escape(performer_lower)}[\]\)】」』]"
        return bool(re.search(bracketed_pattern, title_lower))

    def _extract_video_data_from_html(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912
        """
        Extract video data from YouTube search results HTML.

        Parses the ytInitialData JSON embedded in the page to extract
        complete video objects with properly associated metadata.
        """
        videos = []

        try:
            # Extract ytInitialData JSON from the HTML
            match = re.search(r"var ytInitialData = ({.*?});</script>", html_content)
            if not match:
                logger.debug("ytInitialData not found in HTML")
                return videos

            data = json.loads(match.group(1))

            # Navigate to video results in the JSON structure
            contents = (
                data.get("contents", {})
                .get("twoColumnSearchResultsRenderer", {})
                .get("primaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", [])
            )

            seen_video_ids = set()

            for section in contents:
                items = section.get("itemSectionRenderer", {}).get("contents", [])
                for item in items:
                    if "videoRenderer" not in item:
                        continue

                    video = item["videoRenderer"]
                    video_id = video.get("videoId")

                    # Skip if no video ID or already seen (deduplicate)
                    if not video_id or video_id in seen_video_ids:
                        continue
                    seen_video_ids.add(video_id)

                    # Extract title
                    title_runs = video.get("title", {}).get("runs", [])
                    title = title_runs[0].get("text", "") if title_runs else ""

                    # Extract channel name and ID
                    channel_runs = video.get("ownerText", {}).get("runs", [])
                    channel_name = channel_runs[0].get("text", "") if channel_runs else ""
                    channel_id = ""
                    if channel_runs:
                        browse_endpoint = channel_runs[0].get("navigationEndpoint", {}).get("browseEndpoint", {})
                        channel_id = browse_endpoint.get("browseId", "")

                    # Skip live streams — they have no fixed duration and would
                    # otherwise get stored with a fake 0-second value.
                    if self._is_live_video(video):
                        logger.warning(
                            f"Skipping live video: id={video_id!r} title={title!r} "
                            f"lengthText={video.get('lengthText')!r}"
                        )
                        continue

                    # Extract duration: try simpleText first, then accessibility label.
                    # "simpleText" format: "15:30" or "1:23:45"
                    # "label" format (Japanese): "15 分 30 秒" or "1 時間 26 分 5 秒"
                    # lengthText may be JSON null (Python None) for non-live videos that
                    # lack duration data — use `or {}` to guard against AttributeError.
                    length_text_obj = video.get("lengthText") or {}
                    duration_text = length_text_obj.get("simpleText", "")
                    if not duration_text:
                        duration_text = (
                            length_text_obj.get("accessibility", {}).get("accessibilityData", {}).get("label", "")
                        )
                    duration_seconds = self._parse_duration(duration_text)
                    if duration_seconds == 0 and duration_text:
                        logger.warning(
                            f"Could not parse duration for video id={video_id!r} title={title!r}: "
                            f"duration_text={duration_text!r} lengthText={length_text_obj!r}"
                        )

                    # Extract view count
                    view_text = video.get("viewCountText", {}).get("simpleText", "0")
                    view_count = self._parse_view_count(view_text)

                    video_data = {
                        "video_id": video_id,
                        "title": title,
                        "channel_name": channel_name,
                        "channel_id": channel_id,
                        "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                        "view_count": view_count,
                        "duration_seconds": duration_seconds,
                    }
                    videos.append(video_data)

                    # Limit to first 10 unique results
                    if len(videos) >= 10:  # noqa: PLR2004
                        break

                if len(videos) >= 10:  # noqa: PLR2004
                    break

        except json.JSONDecodeError as e:
            logger.debug(f"Error parsing ytInitialData JSON: {e!s}")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Error extracting video data from HTML: {e!s}")

        return videos

    def channel_matches_performer(self, performer_name: str, channel_name: str, channel_id: str) -> bool:
        """Check if a YouTube channel belongs to the performer.

        Delegates to the shared channel_name_matches() which provides
        substring, fuzzy, and description matching.
        """
        description = self._fetch_channel_description(channel_id) if channel_id else ""
        return channel_name_matches(performer_name, channel_name, description)

    def _fetch_channel_description(self, channel_id: str) -> str:
        """Fetch a YouTube channel's description from its page metadata."""
        url = f"https://www.youtube.com/channel/{channel_id}"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code != requests.codes.ok:
                return ""

            match = re.search(r"var ytInitialData = ({.*?});</script>", response.text)
            if not match:
                return ""

            data = json.loads(match.group(1))
            return data.get("metadata", {}).get("channelMetadataRenderer", {}).get("description", "")
        except Exception:  # noqa: BLE001
            logger.debug(f"Failed to fetch channel description for {channel_id}")
            return ""

    def _parse_view_count(self, view_text: str) -> int:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse view count text like '1,234,567 views' to integer."""
        try:
            # Remove commas and 'views' text, then convert to int
            clean_text = re.sub(r"[^\d]", "", view_text)
            return int(clean_text) if clean_text else 0
        except (ValueError, AttributeError):
            return 0

    def _is_live_video(self, video: dict) -> bool:
        """Return True if this video renderer represents a live stream or premiere.

        Real payload observations (confirmed via confirm_yt_payload):
        - Live streams:  lengthText=null, badges contain BADGE_STYLE_TYPE_LIVE_NOW,
                         thumbnailOverlays is empty [].
        - Shorts:        overlay style='SHORTS', very short durations (filtered naturally).
        - Regular:       overlay style='DEFAULT', lengthText.simpleText present.

        Primary detection is via badge style; overlay style is a secondary signal.
        """
        for badge in video.get("badges", []):
            badge_style = badge.get("metadataBadgeRenderer", {}).get("style", "")
            if "LIVE" in badge_style.upper():
                return True
        for overlay in video.get("thumbnailOverlays", []):
            style = overlay.get("thumbnailOverlayTimeStatusRenderer", {}).get("style", "")
            if style == "LIVE":
                return True
        return False

    def _parse_duration(self, duration_text: str) -> int:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse duration text to seconds.

        Handles two formats from ytInitialData:
        - simpleText:  "3:45" (MM:SS) or "1:23:45" (HH:MM:SS)
        - accessibility label: "3 minutes, 45 seconds" or "1 hour, 23 minutes, 45 seconds"

        Returns 0 when the text is empty or cannot be parsed, so the caller can log and
        exclude the video via the duration filters.
        """
        if not duration_text:
            return 0
        # MM:SS or HH:MM:SS
        if ":" in duration_text:
            try:
                parts = duration_text.split(":")
                if len(parts) == 2:  # noqa: PLR2004
                    return int(parts[0]) * 60 + int(parts[1])
                if len(parts) == 3:  # noqa: PLR2004
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            except ValueError:
                return 0
        # Accessibility label — English: "X hours, Y minutes, Z seconds"
        # Accessibility label — Japanese: "X 時間 Y 分 Z 秒"  (confirmed via confirm_yt_payload)
        hour_match = re.search(r"(\d+)\s*(?:hour|時間)", duration_text, re.IGNORECASE)
        minute_match = re.search(r"(\d+)\s*(?:minute|分)", duration_text, re.IGNORECASE)
        second_match = re.search(r"(\d+)\s*(?:second|秒)", duration_text, re.IGNORECASE)
        if hour_match or minute_match or second_match:
            hours = int(hour_match.group(1)) if hour_match else 0
            minutes = int(minute_match.group(1)) if minute_match else 0
            seconds = int(second_match.group(1)) if second_match else 0
            return hours * 3600 + minutes * 60 + seconds
        # Plain integer seconds
        try:
            return int(float(duration_text))
        except (ValueError, AttributeError):
            return 0


def search_and_create_performer_songs(performer: "Performer") -> list["PerformerSong"]:
    """
    Search for the top 3 most popular YouTube videos for the performer and create PerformerSong instances.

    Also creates a PerformerSocialLink entry for the YouTube channel if channel_id is available.

    Args:
        performer: Performer instance

    Returns:
        List of created PerformerSong instances
    """
    from performers.models import PerformerSocialLink, PerformerSong  # noqa: PLC0415

    # Check if performer already has songs to avoid duplicates
    if performer.songs.filter(youtube_video_id__isnull=False).exclude(youtube_video_id="").exists():
        logger.debug(f"Performer {performer.name} already has YouTube songs")
        return []

    searcher = YouTubeSearcher()
    videos_data = searcher.search_most_popular_videos(performer.name, min_duration_seconds=30, max_results=3)

    if not videos_data:
        logger.debug(f"No suitable YouTube videos found for {performer.name}")
        return []

    created_songs = []
    channel_created = False

    for video_data in videos_data:
        try:
            # Create PerformerSong instance
            song = PerformerSong.objects.create(
                performer=performer,
                title=video_data["title"],
                duration=timedelta(seconds=video_data["duration_seconds"]),
                youtube_video_id=video_data["video_id"],
                youtube_url=video_data["youtube_url"],
                youtube_view_count=video_data["view_count"],
                youtube_duration_seconds=video_data["duration_seconds"],
            )

            logger.info(f"Created song for {performer.name}: {song.title}")
            created_songs.append(song)

            # Create PerformerSocialLink for YouTube channel (only once per performer)
            if not channel_created and video_data.get("channel_id"):
                channel_id = video_data["channel_id"]
                channel_name = video_data.get("channel_name", "")

                if not searcher.channel_matches_performer(performer.name, channel_name, channel_id):
                    logger.debug(
                        f"Channel '{channel_name}' does not match performer '{performer.name}', "
                        "skipping social link creation"
                    )
                    continue

                channel_url = f"https://www.youtube.com/channel/{channel_id}"

                # Check if YouTube social link already exists
                existing_link = PerformerSocialLink.objects.filter(performer=performer, platform="youtube").first()

                if not existing_link:
                    PerformerSocialLink.objects.create(
                        performer=performer,
                        platform="youtube",
                        platform_id=channel_id,
                        url=channel_url,
                    )
                    logger.info(f"Created YouTube social link for {performer.name}: {channel_url}")
                    channel_created = True

        except Exception:  # noqa: BLE001
            logger.exception(f"Failed to create PerformerSong for {performer.name}")
            continue

    return created_songs
