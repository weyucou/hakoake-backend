"""Tests for commons.design — the shared visual system.

These tests cover invariants of the design module that downstream slide
generators depend on. Anything that breaks these tests will silently rot
both the Instagram carousel and the playlist video pipelines.
"""

from __future__ import annotations

from django.test import TestCase
from PIL import Image, ImageDraw

from commons.design import (
    AGED_CREAM,
    FLYER_RED,
    INSTAGRAM_SQUARE,
    PAPER_BLACK,
    VIDEO_WIDESCREEN,
    apply_paper_grain,
    body_font,
    display_font,
    draw_corner_wordmark,
    draw_torn_edge,
    paper_grain,
    scale_to_fill,
    wrap_text,
)

JAPANESE_SAMPLE = "残響のリフレイン"
LATIN_SAMPLE = "HAKKO-AKKEI"


def _text_width(font: object, text: str) -> int:
    img = Image.new("RGB", (1000, 200))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


class TestPalette(TestCase):
    def test_canvas_sizes_are_correct(self) -> None:
        self.assertEqual(INSTAGRAM_SQUARE, (1080, 1080))
        self.assertEqual(VIDEO_WIDESCREEN, (1920, 1080))

    def test_palette_colors_are_3_tuples(self) -> None:
        for color in (PAPER_BLACK, AGED_CREAM, FLYER_RED):
            self.assertEqual(len(color), 3)
            for channel in color:
                self.assertGreaterEqual(channel, 0)
                self.assertLessEqual(channel, 255)


class TestFontLoaders(TestCase):
    def test_display_font_renders_japanese(self) -> None:
        """Display font (Shippori Mincho B1 → Noto Serif CJK) must render JP glyphs."""
        font = display_font(64)
        cjk_width = _text_width(font, JAPANESE_SAMPLE)
        # 8 chars at 64px against any CJK-capable font should clear ~300px
        self.assertGreater(cjk_width, 300)

    def test_display_font_renders_latin(self) -> None:
        font = display_font(64)
        width = _text_width(font, LATIN_SAMPLE)
        self.assertGreater(width, 200)

    def test_body_font_bold_and_regular_resolve(self) -> None:
        bold = body_font(40, bold=True)
        regular = body_font(40, bold=False)
        self.assertIsNotNone(bold)
        self.assertIsNotNone(regular)

    def test_body_font_renders_japanese(self) -> None:
        font = body_font(48, bold=True)
        cjk_width = _text_width(font, JAPANESE_SAMPLE)
        self.assertGreater(cjk_width, 200)


class TestLayoutHelpers(TestCase):
    def test_wrap_text_splits_long_input(self) -> None:
        img = Image.new("RGB", (200, 200))
        draw = ImageDraw.Draw(img)
        font = body_font(32, bold=True)
        lines = wrap_text(draw, "the quick brown fox jumps over the lazy dog", font, max_width=200)
        self.assertGreater(len(lines), 1)

    def test_wrap_text_returns_at_least_one_line_for_unsplittable(self) -> None:
        img = Image.new("RGB", (200, 200))
        draw = ImageDraw.Draw(img)
        font = body_font(120, bold=True)
        lines = wrap_text(draw, "Supercalifragilistic", font, max_width=50)
        self.assertGreaterEqual(len(lines), 1)

    def test_paper_grain_returns_rgba_of_correct_size(self) -> None:
        grain = paper_grain((100, 100))
        self.assertEqual(grain.size, (100, 100))
        self.assertEqual(grain.mode, "RGBA")

    def test_apply_paper_grain_preserves_size_and_mode(self) -> None:
        base = Image.new("RGB", (300, 300), PAPER_BLACK)
        result = apply_paper_grain(base)
        self.assertEqual(result.size, (300, 300))
        self.assertEqual(result.mode, "RGB")

    def test_scale_to_fill_produces_target_size(self) -> None:
        wide = Image.new("RGB", (1920, 600), AGED_CREAM)
        out = scale_to_fill(wide, (500, 500))
        self.assertEqual(out.size, (500, 500))

    def test_draw_torn_edge_does_not_raise(self) -> None:
        img = Image.new("RGB", (400, 400), AGED_CREAM)
        draw = ImageDraw.Draw(img)
        draw_torn_edge(draw, y=200, width=400, color=PAPER_BLACK)

    def test_draw_corner_wordmark_does_not_raise(self) -> None:
        img = Image.new("RGB", (400, 400), PAPER_BLACK)
        draw = ImageDraw.Draw(img)
        for anchor in ("lt", "rt", "lb", "rb"):
            draw_corner_wordmark(draw, (200, 200), anchor=anchor)
