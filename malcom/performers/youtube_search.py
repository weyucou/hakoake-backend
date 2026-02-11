import json
import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING

import requests

from .normalization import normalize_performer_name

if TYPE_CHECKING:
    from .models import Performer, PerformerSong

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

    def _extract_video_data_from_html(self, html_content: str) -> list[dict]:
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

                    # Extract duration
                    duration_text = video.get("lengthText", {}).get("simpleText", "0:00")
                    duration_seconds = self._parse_duration(duration_text)

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

        Checks normalized channel name first (preferred), then falls back to
        the channel page description.
        """
        normalized_performer = normalize_performer_name(performer_name)
        normalized_channel = normalize_performer_name(channel_name)

        if normalized_performer in normalized_channel:
            return True

        if channel_id:
            description = self._fetch_channel_description(channel_id)
            normalized_description = normalize_performer_name(description)
            if normalized_performer in normalized_description:
                return True

        return False

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

    def _parse_duration(self, duration_text: str) -> int:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse duration text like '3:45' to seconds."""
        try:
            if ":" in duration_text:
                parts = duration_text.split(":")
                if len(parts) == 2:  # noqa: PLR2004  # MM:SS
                    minutes, seconds = int(parts[0]), int(parts[1])
                    return minutes * 60 + seconds
                if len(parts) == 3:  # noqa: PLR2004  # HH:MM:SS
                    hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
                    return hours * 3600 + minutes * 60 + seconds
            return int(float(duration_text))  # If it's just a number
        except (ValueError, AttributeError):
            return 30  # Default to 30 seconds if parsing fails


def search_and_create_performer_songs(performer: "Performer") -> list["PerformerSong"]:
    """
    Search for the top 3 most popular YouTube videos for the performer and create PerformerSong instances.

    Also creates a PerformerSocialLink entry for the YouTube channel if channel_id is available.

    Args:
        performer: Performer instance

    Returns:
        List of created PerformerSong instances
    """
    from .models import PerformerSocialLink, PerformerSong  # noqa: PLC0415

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
