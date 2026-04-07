"""Tests for the Instagram image generator's font handling.

The historical bug: instagram_images.py hardcoded DejaVu Sans, which has zero
Japanese coverage, so every kana/kanji rendered as .notdef tofu boxes. These
tests assert that Japanese glyphs render with real (non-notdef) widths.
"""

from django.test import TestCase
from PIL import Image, ImageDraw, ImageFont

from commons.instagram_images import _font

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
