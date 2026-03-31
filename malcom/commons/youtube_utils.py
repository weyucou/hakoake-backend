"""Shared YouTube API utilities for playlist management commands."""

import logging
import pickle
from pathlib import Path

import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)

DEFAULT_SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


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
