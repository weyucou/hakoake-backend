"""Tests for the performers app."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from performers.image_fetcher import PerformerImageFetcher
from performers.models import Performer


class PerformerImageFetcherTestCase(TestCase):
    """Test cases for PerformerImageFetcher."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.fetcher = PerformerImageFetcher()

    @patch("performers.image_fetcher.requests.Session.get")
    def test_search_theaudiodb_success(self, mock_get: MagicMock) -> None:
        """Test successful search on TheAudioDB."""
        # Mock API response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "artists": [
                {
                    "strArtist": "Coldplay",
                    "strArtistThumb": "https://example.com/thumb.jpg",
                    "strArtistLogo": "https://example.com/logo.png",
                    "strArtistFanart": "https://example.com/fanart.jpg",
                    "strArtistBanner": "https://example.com/banner.jpg",
                }
            ]
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.fetcher.search_theaudiodb("Coldplay")

        self.assertIsNotNone(result)
        self.assertEqual(result.get("name"), "Coldplay")
        self.assertEqual(result.get("thumb"), "https://example.com/thumb.jpg")
        self.assertEqual(result.get("logo"), "https://example.com/logo.png")

    @patch("performers.image_fetcher.requests.Session.get")
    def test_search_theaudiodb_not_found(self, mock_get: MagicMock) -> None:
        """Test search when artist is not found."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"artists": None}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.fetcher.search_theaudiodb("NonexistentArtist")

        self.assertEqual(result, {})

    @patch("performers.image_fetcher.requests.Session.get")
    def test_download_image_content_success(self, mock_get: MagicMock) -> None:
        """Test successful image download."""
        # Mock image content
        fake_image_data = b"fake_image_content"
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [fake_image_data]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.fetcher.download_image_content("https://example.com/image.jpg")

        self.assertEqual(result, fake_image_data)

    def test_download_image_content_empty_url(self) -> None:
        """Test download with empty URL."""
        result = self.fetcher.download_image_content("")
        self.assertIsNone(result)

    @patch("performers.image_fetcher.PerformerImageFetcher.download_image_content")
    @patch("performers.image_fetcher.PerformerImageFetcher.search_theaudiodb")
    def test_fetch_and_save_images(self, mock_search: MagicMock, mock_download: MagicMock) -> None:
        """Test fetching and saving images to performer."""
        # Create a performer
        performer = Performer(
            name="Test Artist",
            name_kana="テストアーティスト",
            name_romaji="Test Artist",
        )
        performer._skip_image_fetch = True  # Skip automatic image fetch in save
        performer.save()

        # Mock search results
        mock_search.return_value = {
            "name": "Test Artist",
            "thumb": "https://example.com/thumb.jpg",
            "logo": "https://example.com/logo.png",
        }

        # Mock image download
        mock_download.return_value = b"fake_image_data"

        # Fetch and save images
        results = self.fetcher.fetch_and_save_images(performer)

        # Verify results
        self.assertTrue(results["performer_image"])
        self.assertTrue(results["logo_image"])
        self.assertTrue(performer.performer_image)
        self.assertTrue(performer.logo_image)


class PerformerImageIntegrationTestCase(TestCase):
    """Integration tests for automatic image fetching on Performer creation."""

    @patch("performers.image_fetcher.PerformerImageFetcher.search_theaudiodb")
    @patch("performers.image_fetcher.PerformerImageFetcher.download_image_content")
    def test_performer_creation_triggers_image_fetch(self, mock_download: MagicMock, mock_search: MagicMock) -> None:
        """Test that creating a performer automatically triggers image fetching."""
        # Mock search results
        mock_search.return_value = {
            "name": "Auto Fetch Artist",
            "thumb": "https://example.com/thumb.jpg",
            "logo": "https://example.com/logo.png",
        }

        # Mock image download
        mock_download.return_value = b"fake_image_data"

        # Create performer (should automatically fetch images)
        performer = Performer(
            name="Auto Fetch Artist",
            name_kana="オートフェッチアーティスト",
            name_romaji="Auto Fetch Artist",
        )
        performer.save()

        # Reload from database
        performer.refresh_from_db()

        # Verify images were fetched and saved
        # Note: The actual save happens in fetch_and_update_performer_images
        mock_search.assert_called_once()

    def test_performer_with_skip_flag(self) -> None:
        """Test that _skip_image_fetch flag prevents automatic fetching."""
        performer = Performer(
            name="Skip Fetch Artist",
            name_kana="スキップフェッチアーティスト",
            name_romaji="Skip Fetch Artist",
        )
        performer._skip_image_fetch = True
        performer.save()

        # Verify no images were fetched
        self.assertFalse(performer.performer_image)
        self.assertFalse(performer.logo_image)
