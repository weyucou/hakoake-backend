"""Tests for shared utilities in commons.functions."""

from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase

from commons.functions import CatboxUploadError, upload_to_catbox


class TestUploadToCatbox(TestCase):
    @patch("commons.functions.requests.post")
    def test_returns_https_url_on_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200, text="https://files.catbox.moe/abc123.jpg\n")

        url = upload_to_catbox(b"\xff\xd8\xff\xe0fake-jpeg", "cover.jpg")

        self.assertEqual(url, "https://files.catbox.moe/abc123.jpg")
        mock_post.assert_called_once()
        _args, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"], {"reqtype": "fileupload"})
        self.assertIn("fileToUpload", kwargs["files"])
        filename, _bytes, content_type = kwargs["files"]["fileToUpload"]
        self.assertEqual(filename, "cover.jpg")
        self.assertEqual(content_type, "image/jpeg")

    @patch("commons.functions.requests.post")
    def test_raises_descriptive_error_on_http_failure(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")

        with self.assertRaises(CatboxUploadError) as cm:
            upload_to_catbox(b"jpeg-bytes", "flyer_01.jpg")

        self.assertIn("flyer_01.jpg", str(cm.exception))
        self.assertIn("500", str(cm.exception))

    @patch("commons.functions.requests.post")
    def test_raises_on_network_error(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = requests.ConnectionError("dns failure")

        with self.assertRaises(CatboxUploadError) as cm:
            upload_to_catbox(b"jpeg-bytes", "qr_02.jpg")

        self.assertIn("qr_02.jpg", str(cm.exception))
        self.assertIn("dns failure", str(cm.exception))

    @patch("commons.functions.requests.post")
    def test_raises_when_response_is_not_https_url(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(status_code=200, text="something went wrong")

        with self.assertRaises(CatboxUploadError) as cm:
            upload_to_catbox(b"jpeg-bytes", "x.jpg")

        self.assertIn("x.jpg", str(cm.exception))
