"""Tests for shared utilities in commons.functions."""

from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase

from commons.functions import LITTERBOX_TTL, LitterboxUploadError, upload_to_litterbox


class TestUploadToLitterbox(TestCase):
    @patch("commons.functions.requests.post")
    def test_returns_https_url_on_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200, text="https://litter.catbox.moe/abc123.jpg\n")

        url = upload_to_litterbox(b"\xff\xd8\xff\xe0fake-jpeg", "cover.jpg")

        self.assertEqual(url, "https://litter.catbox.moe/abc123.jpg")
        mock_post.assert_called_once()
        _args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"], {"reqtype": "fileupload", "time": LITTERBOX_TTL})
        self.assertIn("fileToUpload", kwargs["files"])
        filename, _bytes, content_type = kwargs["files"]["fileToUpload"]
        self.assertEqual(filename, "cover.jpg")
        self.assertEqual(content_type, "image/jpeg")

    @patch("commons.functions.requests.post")
    def test_sends_time_field_as_1h(self, mock_post: MagicMock) -> None:
        """Regression: litterbox requires the ``time`` field; omission yields HTTP 400."""
        mock_post.return_value = MagicMock(status_code=200, text="https://litter.catbox.moe/abc123.jpg")

        upload_to_litterbox(b"jpeg-bytes", "flyer.jpg")

        _args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"].get("time"), "1h")

    @patch("commons.functions.requests.post")
    def test_raises_descriptive_error_on_http_failure(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")

        with self.assertRaises(LitterboxUploadError) as cm:
            upload_to_litterbox(b"jpeg-bytes", "flyer_01.jpg")

        self.assertIn("flyer_01.jpg", str(cm.exception))
        self.assertIn("500", str(cm.exception))

    @patch("commons.functions.requests.post")
    def test_raises_on_network_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = requests.ConnectionError("dns failure")

        with self.assertRaises(LitterboxUploadError) as cm:
            upload_to_litterbox(b"jpeg-bytes", "qr_02.jpg")

        self.assertIn("qr_02.jpg", str(cm.exception))
        self.assertIn("dns failure", str(cm.exception))

    @patch("commons.functions.requests.post")
    def test_raises_when_response_is_not_https_url(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200, text="something went wrong")

        with self.assertRaises(LitterboxUploadError) as cm:
            upload_to_litterbox(b"jpeg-bytes", "x.jpg")

        self.assertIn("x.jpg", str(cm.exception))
