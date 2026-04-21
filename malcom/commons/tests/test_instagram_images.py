"""Tests for the Instagram image generator's font handling and combined slide generation.

The historical bug: instagram_images.py hardcoded DejaVu Sans, which has zero
Japanese coverage, so every kana/kanji rendered as .notdef tofu boxes. These
tests assert that Japanese glyphs render with real (non-notdef) widths.
"""

import io
from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase
from PIL import Image, ImageDraw, ImageFont

from commons.design import PAPER_BLACK
from commons.instagram_images import (
    IMG_H,
    IMG_W,
    _font,
    generate_combined_flyer_qr_slide,
    generate_performer_card,
)

JAPANESE_SAMPLE = "残響のリフレイン"
LATIN_SAMPLE = "HAKKO-AKKEI"


def _text_width(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> int:
    img = Image.new("RGB", (1000, 200))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


class TestFontFallback(TestCase):
    def test_renders_japanese_with_non_trivial_width(self) -> None:
        """If the resolved font lacks Japanese glyphs, every char becomes .notdef
        and the rendered width is dramatically smaller than what a CJK font produces.
        Compare against a known-bad Latin-only font to detect the regression.
        """
        font = _font(64, bold=True)
        cjk_width = _text_width(font, JAPANESE_SAMPLE)

        # DejaVu Sans Bold renders Japanese as .notdef boxes (or zero width).
        # If the resolved _font() also fell through to DejaVu, the widths would match.
        try:
            dejavu = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        except OSError:
            self.skipTest("DejaVu Sans Bold not present — cannot establish comparison baseline")
        dejavu_width = _text_width(dejavu, JAPANESE_SAMPLE)

        self.assertGreater(
            cjk_width,
            dejavu_width,
            f"Japanese rendered width {cjk_width}px is not greater than DejaVu's {dejavu_width}px — "
            "_font() is falling back to a Latin-only font and Japanese glyphs are tofu boxes",
        )

    def test_renders_latin_with_non_trivial_width(self) -> None:
        """The fallback chain should also render Latin text legibly."""
        font = _font(64, bold=True)
        width = _text_width(font, LATIN_SAMPLE)
        # 11 chars at 64px should be at least ~200 pixels wide for any reasonable font
        self.assertGreater(width, 200, f"Latin '{LATIN_SAMPLE}' rendered absurdly narrow ({width}px)")

    def test_bold_and_regular_both_resolve(self) -> None:
        """Both font weights must produce a usable font (never raise)."""
        bold = _font(40, bold=True)
        regular = _font(40, bold=False)
        self.assertIsNotNone(bold)
        self.assertIsNotNone(regular)


def _make_dummy_flyer_bytes() -> bytes:
    """Create a minimal JPEG image to use as a flyer input."""
    img = Image.new("RGB", (800, 600), (100, 50, 150))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class TestCombinedFlyerQrSlide(TestCase):
    def test_returns_valid_jpeg(self) -> None:
        """The combined slide must return loadable JPEG bytes."""
        result = generate_combined_flyer_qr_slide(
            flyer_bytes=_make_dummy_flyer_bytes(),
            url="https://example.com/event/1",
            position=3,
            performer_name="残響のリフレイン",
            venue_name="下北沢SHELTER",
            event_name="Spring Live 2026",
            event_date=date(2026, 4, 15),
        )
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 1000)
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (IMG_W, IMG_H))

    def test_renders_without_event_name(self) -> None:
        """Combined slide must not crash when event_name is empty."""
        result = generate_combined_flyer_qr_slide(
            flyer_bytes=_make_dummy_flyer_bytes(),
            url="https://example.com",
            position=1,
            performer_name="TestBand",
            venue_name="Shibuya WWW",
            event_name="",
            event_date=date(2026, 4, 10),
        )
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 1000)

    def test_renders_with_non_square_flyer(self) -> None:
        """Non-square flyer images should be scaled/cropped to 1080x1080."""
        wide_img = Image.new("RGB", (1920, 1080), (200, 100, 50))
        buf = io.BytesIO()
        wide_img.save(buf, format="JPEG")
        result = generate_combined_flyer_qr_slide(
            flyer_bytes=buf.getvalue(),
            url="https://example.com",
            position=5,
            performer_name="WideImage Band",
            venue_name="Shinjuku LOFT",
            event_name="Wide Show",
            event_date=date(2026, 5, 1),
        )
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (IMG_W, IMG_H))


def _is_near_paper_black(pixel: tuple[int, int, int], tolerance: int = 15) -> bool:
    """True if the pixel's per-channel sum-of-diffs vs PAPER_BLACK is within tolerance."""
    return sum(abs(pixel[i] - PAPER_BLACK[i]) for i in range(3)) <= tolerance


class TestPerformerCardFallback(TestCase):
    """Regression guard for #57: insta-background.png must be used when no performer/event image exists.

    Commit 7b7dbd5 (design-system refactor) dropped the insta-background.png
    step originally introduced in b8aced6, so the fallback chain jumped
    straight to solid PAPER_BLACK.
    """

    def _make_performer_with_no_images(self) -> MagicMock:
        performer = MagicMock()
        performer.name = "TestBand"
        performer.name_romaji = ""
        for field in ("performer_image", "fanart_image", "banner_image", "logo_image"):
            empty_field = MagicMock()
            empty_field.name = ""
            setattr(performer, field, empty_field)
        return performer

    def test_uses_insta_background_when_performer_and_brand_bg_unavailable(self) -> None:
        """With no performer images AND brand background patched to None, the photo
        region must still have colour — proving insta-background.png was applied.
        """
        performer = self._make_performer_with_no_images()

        with patch("commons.instagram_images.load_brand_background", return_value=None):
            result = generate_performer_card(performer, position=1, schedules=[])

        img = Image.open(io.BytesIO(result)).convert("RGB")
        self.assertEqual(img.size, (IMG_W, IMG_H))

        # Sample pixels from the top third of the photo region (62% of IMG_H).
        # Paper grain adds ~1-2 units of jitter, so we tolerate 15 units of
        # per-channel total drift when classifying a pixel as "near PAPER_BLACK".
        photo_h = int(IMG_H * 0.62)
        sample_y = photo_h // 4
        pixels = [img.getpixel((x, sample_y)) for x in range(20, IMG_W, IMG_W // 16)]
        non_black = [px for px in pixels if not _is_near_paper_black(px)]
        self.assertGreater(
            len(non_black),
            len(pixels) // 2,
            f"Performer card photo region fell through to solid PAPER_BLACK at row {sample_y}; "
            f"insta-background.png fallback not applied. Sampled pixels: {pixels}",
        )
