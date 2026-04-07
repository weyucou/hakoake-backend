"""Shared YouTube API utilities for playlist management commands."""

import logging
import pickle
import re
from pathlib import Path

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import googleapiclient.http
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

DEFAULT_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
VIDEOS_LIST_BATCH_SIZE = 50  # YouTube Data API videos.list max ids per call

_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_iso8601_duration(duration: str) -> int:
    """Parse a YouTube ISO 8601 duration (e.g. ``PT1H2M3S``) to total seconds.

    Returns 0 if the string cannot be parsed.
    """
    match = _ISO8601_DURATION_RE.fullmatch(duration or "")
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def get_authorized_youtube_client(client_secrets_file: Path, scopes: list[str] | None = None):
    """Get an authorized YouTube API client."""
    api_service_name = "youtube"
    api_version = "v3"

    scopes = scopes or DEFAULT_SCOPES
    token_cache_file = client_secrets_file.parent / "token.pickle"

    credentials = None

    # Load existing credentials from cache if available
    if token_cache_file.exists():
        logger.info(f"Loading cached credentials from {token_cache_file}")
        try:
            credentials = pickle.loads(token_cache_file.read_bytes())  # noqa: S301
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to load cached credentials: {e}")
            credentials = None

    # Refresh expired credentials
    if credentials and not credentials.valid and credentials.refresh_token:
        logger.info("Refreshing expired credentials")
        try:
            credentials.refresh(Request())
            logger.info("Successfully refreshed credentials")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to refresh credentials: {e}")
            credentials = None

    # Run OAuth flow if no valid credentials
    if not credentials or not credentials.valid:
        logger.info("Running OAuth flow for new credentials")
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), scopes)
        credentials = flow.run_local_server(port=0)
        logger.info("Successfully obtained new credentials")

        # Save credentials to cache
        try:
            token_cache_file.write_bytes(pickle.dumps(credentials))
            logger.info(f"Saved credentials to cache: {token_cache_file}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to save credentials to cache: {e}")

    # Build and return YouTube API client
    youtube = googleapiclient.discovery.build(api_service_name, api_version, credentials=credentials)
    return youtube


def create_youtube_playlist(title: str, description: str, client_secrets_file: Path) -> str:
    """Create a new public YouTube playlist and return its ID."""
    youtube = get_authorized_youtube_client(client_secrets_file)

    request = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
            },
            "status": {"privacyStatus": "public"},
        },
    )

    response = request.execute()
    playlist_id = response["id"]
    logger.info(f"Created YouTube playlist: {title} (ID: {playlist_id})")
    return playlist_id


def update_youtube_playlist(playlist_id: str, title: str, description: str, client_secrets_file: Path) -> None:
    """Update an existing YouTube playlist's title and description."""
    youtube = get_authorized_youtube_client(client_secrets_file)

    request = youtube.playlists().update(
        part="snippet",
        body={
            "id": playlist_id,
            "snippet": {
                "title": title,
                "description": description,
            },
        },
    )
    request.execute()
    logger.info(f"Updated YouTube playlist: {title} (ID: {playlist_id})")


def list_playlist_items(playlist_id: str, client_secrets_file: Path) -> list[dict]:
    """Return all items in a YouTube playlist as a list of dicts with 'playlist_item_id' and 'video_id'."""
    youtube = get_authorized_youtube_client(client_secrets_file)
    items = []
    next_page_token = None
    while True:
        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token,
        )
        response = request.execute()
        for item in response.get("items", []):
            items.append(
                {
                    "playlist_item_id": item["id"],
                    "video_id": item["snippet"]["resourceId"]["videoId"],
                    "title": item["snippet"].get("title", ""),
                }
            )
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    logger.info(f"Listed {len(items)} items in playlist {playlist_id}")
    return items


def get_video_durations(video_ids: list[str], client_secrets_file: Path) -> dict[str, int]:
    """Fetch actual durations (in seconds) for the given YouTube video IDs.

    Returns a dict mapping ``video_id`` -> ``duration_seconds``. Videos that
    are deleted, private, or otherwise unavailable will be omitted from the
    result. Empty input returns an empty dict.

    Batches IDs into groups of ``VIDEOS_LIST_BATCH_SIZE`` (the YouTube API
    ``videos.list`` per-call maximum).
    """
    if not video_ids:
        return {}

    youtube = get_authorized_youtube_client(client_secrets_file)
    durations: dict[str, int] = {}
    for start in range(0, len(video_ids), VIDEOS_LIST_BATCH_SIZE):
        batch = video_ids[start : start + VIDEOS_LIST_BATCH_SIZE]
        try:
            response = youtube.videos().list(part="contentDetails", id=",".join(batch)).execute()
        except googleapiclient.errors.HttpError:
            logger.exception(f"Failed to fetch durations for batch starting at index {start}")
            continue
        for item in response.get("items", []):
            video_id = item["id"]
            iso_duration = item.get("contentDetails", {}).get("duration", "")
            durations[video_id] = parse_iso8601_duration(iso_duration)
    logger.info(f"Fetched durations for {len(durations)}/{len(video_ids)} videos")
    return durations


def remove_playlist_item(playlist_item_id: str, client_secrets_file: Path) -> bool:
    """Remove a specific item from a YouTube playlist by its playlistItem ID."""
    youtube = get_authorized_youtube_client(client_secrets_file)
    try:
        youtube.playlistItems().delete(id=playlist_item_id).execute()
    except googleapiclient.errors.HttpError:
        logger.exception(f"Failed to remove playlist item {playlist_item_id}")
        return False
    else:
        logger.info(f"Removed playlist item {playlist_item_id}")
        return True


def upload_video_to_youtube(
    video_path: Path,
    title: str,
    description: str,
    client_secrets_file: Path,
    privacy_status: str = "public",
) -> str:
    """Upload a local video file to YouTube and return its video ID."""
    youtube = get_authorized_youtube_client(client_secrets_file)

    body = {
        "snippet": {
            "title": title,
            "description": description,
        },
        "status": {
            "privacyStatus": privacy_status,
        },
    }

    media = googleapiclient.http.MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    logger.info(f"Uploaded video: {title} (ID: {video_id})")
    return video_id


def insert_video_at_position(playlist_id: str, video_id: str, position: int, client_secrets_file: Path) -> bool:
    """Insert a video at a specific (0-based) position in a YouTube playlist."""
    youtube = get_authorized_youtube_client(client_secrets_file)

    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "position": position,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                },
            },
        ).execute()
    except googleapiclient.errors.HttpError:
        logger.exception(f"Failed to insert video {video_id} at position {position} in playlist {playlist_id}")
        return False
    else:
        logger.info(f"Inserted video {video_id} at position {position} in playlist {playlist_id}")
        return True


def add_video_to_playlist(playlist_id: str, video_id: str, client_secrets_file: Path) -> bool:
    """Add a video to a YouTube playlist."""
    youtube = get_authorized_youtube_client(client_secrets_file)

    try:
        request = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                },
            },
        )
        request.execute()
    except googleapiclient.errors.HttpError:
        logger.exception(f"Failed to add video {video_id} to playlist")
        return False
    else:
        logger.info(f"Added video {video_id} to playlist {playlist_id}")
        return True
