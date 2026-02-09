"""
Fetch performer images from TheAudioDB and other sources.

Integrated from the standalone artist_image_fetcher.py script.
"""

import logging
from io import BytesIO
from typing import TYPE_CHECKING

import requests
from django.core.files.base import ContentFile

if TYPE_CHECKING:
    from .models import Performer

logger = logging.getLogger(__name__)


class PerformerImageFetcher:
    """Fetches performer images and logos from TheAudioDB API with MusicBrainz fallback."""

    # TheAudioDB API (free tier)
    TADB_API_KEY = "2"  # Public test key
    TADB_SEARCH_URL = "https://www.theaudiodb.com/api/v1/json/{api_key}/search.php"

    # MusicBrainz API
    MB_SEARCH_URL = "https://musicbrainz.org/ws/2/artist/"
    MB_HEADERS = {"User-Agent": "PerformerImageFetcher/1.0"}

    def __init__(self) -> None:
        """Initialize the fetcher with a requests session."""
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "PerformerImageFetcher/1.0"})

    def search_theaudiodb(self, artist_name: str) -> dict[str, str | None]:
        """
        Search TheAudioDB for artist information and image URLs.

        Args:
            artist_name: Name of the artist to search for

        Returns:
            Dictionary with image URLs (thumb, logo, fanart, banner) or empty dict
        """
        try:
            url = self.TADB_SEARCH_URL.format(api_key=self.TADB_API_KEY)
            params = {"s": artist_name}

            logger.debug(f"Searching TheAudioDB for artist: {artist_name}")
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            if data.get("artists") and len(data["artists"]) > 0:
                artist = data["artists"][0]
                logger.info(f"Found {artist.get('strArtist')} on TheAudioDB")
                return {
                    "name": artist.get("strArtist"),
                    "thumb": artist.get("strArtistThumb"),
                    "logo": artist.get("strArtistLogo"),
                    "fanart": artist.get("strArtistFanart"),
                    "banner": artist.get("strArtistBanner"),
                }
            logger.debug(f"Artist {artist_name} not found on TheAudioDB")
            return {}  # noqa: TRY300

        except Exception:  # noqa: BLE001
            logger.exception(f"Error searching TheAudioDB for {artist_name}")
            return {}

    def search_musicbrainz(self, artist_name: str) -> dict[str, str | None]:
        """
        Search MusicBrainz for artist information as a fallback.

        MusicBrainz provides artist confirmation and MBID but no direct image links.

        Args:
            artist_name: Name of the artist to search for

        Returns:
            Dictionary with artist name, MBID, and score, or empty dict
        """
        try:
            params = {"query": f'artist:"{artist_name}"', "fmt": "json", "limit": 1}

            logger.debug(f"Searching MusicBrainz for artist: {artist_name}")
            response = self.session.get(self.MB_SEARCH_URL, params=params, headers=self.MB_HEADERS, timeout=10)
            response.raise_for_status()

            data = response.json()
            if data.get("artists") and len(data["artists"]) > 0:
                artist = data["artists"][0]
                logger.info(
                    f"Found {artist.get('name')} on MusicBrainz "
                    f"(MBID: {artist.get('id')}, score: {artist.get('score')})"
                )
                return {
                    "name": artist.get("name"),
                    "mbid": artist.get("id"),
                    "score": artist.get("score"),
                }
            logger.debug(f"Artist {artist_name} not found on MusicBrainz")
            return {}  # noqa: TRY300

        except Exception:  # noqa: BLE001
            logger.exception(f"Error searching MusicBrainz for {artist_name}")
            return {}

    def download_image_content(self, url: str) -> bytes | None:
        """
        Download image content from a URL.

        Args:
            url: URL of the image to download

        Returns:
            Image bytes or None if download fails
        """
        if not url:
            return None

        try:
            logger.debug(f"Downloading image from {url}")
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()

            # Read image content into memory
            image_content = BytesIO()
            for chunk in response.iter_content(chunk_size=8192):
                image_content.write(chunk)

            image_bytes = image_content.getvalue()
            logger.debug(f"Downloaded {len(image_bytes)} bytes")

        except Exception:  # noqa: BLE001
            logger.exception(f"Failed to download image from {url}")
            return None
        else:
            return image_bytes

    # Mapping from TheAudioDB response keys to (model field, default extension)
    IMAGE_FIELD_MAP: list[tuple[str, str, str]] = [
        ("thumb", "performer_image", "jpg"),
        ("logo", "logo_image", "png"),
        ("fanart", "fanart_image", "jpg"),
        ("banner", "banner_image", "jpg"),
    ]

    def _save_image_to_field(self, performer: "Performer", field_name: str, url: str, extension: str) -> bool:
        """Download an image and save it to a performer's ImageField."""
        image_bytes = self.download_image_content(url)
        if not image_bytes:
            return False

        try:
            # For logo, detect extension from URL
            if field_name == "logo_image" and ".png" not in url.lower():
                extension = "jpg"
            filename = f"{performer.name}_{field_name}.{extension}"
            getattr(performer, field_name).save(filename, ContentFile(image_bytes), save=False)
            logger.info(f"Saved {field_name} for {performer.name}")
        except Exception:  # noqa: BLE001
            logger.exception(f"Failed to save {field_name} for {performer.name}")
            return False
        else:
            return True

    def fetch_and_save_images(self, performer: "Performer") -> dict[str, bool]:
        """
        Fetch and save performer images to the Performer model.

        Args:
            performer: Performer instance to update with images

        Returns:
            Dictionary mapping image types to success status
        """
        results = {field: False for _, field, _ in self.IMAGE_FIELD_MAP}

        # Search TheAudioDB for artist data
        artist_data = self.search_theaudiodb(performer.name)

        if not artist_data:
            # Fallback to MusicBrainz for artist confirmation
            mb_data = self.search_musicbrainz(performer.name)
            if mb_data:
                logger.info(
                    f"MusicBrainz confirmed artist {mb_data.get('name')} "
                    f"(MBID: {mb_data.get('mbid')}), but no images available"
                )
            else:
                logger.debug(f"No image data found for {performer.name}")
            return results

        for api_key, field_name, extension in self.IMAGE_FIELD_MAP:
            url = artist_data.get(api_key)
            if url:
                results[field_name] = self._save_image_to_field(performer, field_name, url, extension)

        return results


def fetch_and_update_performer_images(performer: "Performer") -> dict[str, bool]:
    """
    Fetch and update images for a performer.

    This function is called automatically when a new Performer is created.

    Args:
        performer: Performer instance

    Returns:
        Dictionary mapping image types to success status
    """
    image_fields = ["performer_image", "logo_image", "fanart_image", "banner_image"]

    # Skip if performer already has all images
    if all(getattr(performer, field) for field in image_fields):
        logger.debug(f"Performer {performer.name} already has all images")
        return dict.fromkeys(image_fields, True)

    fetcher = PerformerImageFetcher()
    results = fetcher.fetch_and_save_images(performer)

    # Save the performer if any images were added
    if any(results.values()):
        try:
            performer.save(update_fields=image_fields)
            logger.info(f"Updated performer {performer.name} with images")
        except Exception:  # noqa: BLE001
            logger.exception(f"Failed to save performer {performer.name} after updating images")

    return results
