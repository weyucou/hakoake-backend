"""Unit tests for commons/instagram_images.py — generate_qr_slide and helpers."""

from __future__ import annotations

import io
from datetime import date

from commons.instagram_images import _resize_to_square, generate_qr_slide
from django.test import TestCase
from PIL import Image


class TestResizeToSquare(TestCase):
    def _make_jpeg(self, w: int, h: int) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (w, h), color=(100, 150, 200)).save(buf, format="JPEG")
        return buf.getvalue()

    def test_square_input_unchanged_size(self) -> None:
        raw = self._make_jpeg(800, 800)
        result = _resize_to_square(raw, 1080)
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (1080, 1080))

    def test_wide_image_becomes_square(self) -> None:
        raw = self._make_jpeg(1920, 1080)
        result = _resize_to_square(raw, 1080)
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (1080, 1080))

    def test_tall_image_becomes_square(self) -> None:
        raw = self._make_jpeg(600, 1200)
        result = _resize_to_square(raw, 1080)
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (1080, 1080))

    def test_returns_jpeg_bytes(self) -> None:
        raw = self._make_jpeg(400, 400)
        result = _resize_to_square(raw, 200)
        self.assertEqual(result[:2], b"\xff\xd8")


class TestGenerateQrSlide(TestCase):
    def _slide(self, **kwargs) -> bytes:
        defaults = {
            "url": "https://hakoake.com/performer/1/",
            "position": 1,
            "performer_name": "TestBand",
            "venue_name": "Club Malcom",
            "event_name": "Spring Live 2026",
            "event_date": date(2026, 4, 5),
        }
        defaults.update(kwargs)
        return generate_qr_slide(**defaults)

    def test_returns_jpeg_bytes(self) -> None:
        result = self._slide()
        self.assertIsInstance(result, bytes)
        self.assertEqual(result[:2], b"\xff\xd8")

    def test_output_is_1080x1080(self) -> None:
        result = self._slide()
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (1080, 1080))

    def test_non_empty_output(self) -> None:
        result = self._slide()
        self.assertGreater(len(result), 10_000)

    def test_empty_event_name_does_not_crash(self) -> None:
        result = self._slide(event_name="")
        self.assertIsInstance(result, bytes)
        self.assertEqual(result[:2], b"\xff\xd8")

    def test_long_performer_name(self) -> None:
        result = self._slide(performer_name="A" * 50)
        self.assertIsInstance(result, bytes)
