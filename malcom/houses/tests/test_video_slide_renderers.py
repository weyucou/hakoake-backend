"""Smoke tests for the playlist video slide renderers in houses.functions.

The renderers replaced the previous create_slide() closure inside
_generate_playlist_video. They produce 1920×1080 PIL images that the moviepy
pipeline turns into video clips. These tests confirm the renderers don't
crash on representative input and that they emit images of the expected size.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.test import TestCase
from PIL import Image

from houses.functions import (
    render_video_closing_slide,
    render_video_intro_slide,
    render_video_performer_slide,
)

VIDEO_SIZE = (1920, 1080)


class TestRenderVideoIntroSlide(TestCase):
    def test_intro_with_full_lineup(self) -> None:
        lineup = [
            (1, "残響のリフレイン", True),
            (2, "OGRE YOU ASSHOLE", False),
            (3, "tricot", False),
            (4, "Mass of the Fermenting Dregs", False),
            (5, "envy", True),
            (6, "toe", False),
        ]
        img = render_video_intro_slide(title_label="April 2026", lineup=lineup)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, VIDEO_SIZE)

    def test_intro_with_empty_lineup(self) -> None:
        img = render_video_intro_slide(title_label="April 2026", lineup=[])
        self.assertEqual(img.size, VIDEO_SIZE)

    def test_intro_with_single_entry(self) -> None:
        img = render_video_intro_slide(
            title_label="Week of 2026-04-13",
            lineup=[(1, "tricot", False)],
        )
        self.assertEqual(img.size, VIDEO_SIZE)


def _stub_performer(name: str = "残響のリフレイン", romaji: str = "ZANKYO NO REFRAIN") -> SimpleNamespace:
    return SimpleNamespace(name=name, name_romaji=romaji)


class TestRenderVideoPerformerSlide(TestCase):
    def test_performer_with_all_fields(self) -> None:
        img = render_video_performer_slide(
            position=3,
            performer=_stub_performer(),
            song_title="Crimson Tide",
            venue_name="下北沢SHELTER",
            performance_date=date(2026, 4, 15),
            artist_url="https://example.com/artist",
            venue_url="https://example.com/venue",
        )
        self.assertEqual(img.size, VIDEO_SIZE)

    def test_performer_with_no_qr_targets(self) -> None:
        img = render_video_performer_slide(
            position=1,
            performer=_stub_performer(),
            song_title="",
            venue_name=None,
            performance_date=None,
            artist_url=None,
            venue_url=None,
        )
        self.assertEqual(img.size, VIDEO_SIZE)

    def test_performer_with_only_artist_qr(self) -> None:
        img = render_video_performer_slide(
            position=2,
            performer=_stub_performer(),
            song_title="A Song",
            venue_name="Shibuya WWW",
            performance_date=date(2026, 4, 20),
            artist_url="https://example.com/artist",
            venue_url=None,
        )
        self.assertEqual(img.size, VIDEO_SIZE)

    def test_performer_with_no_romaji(self) -> None:
        img = render_video_performer_slide(
            position=4,
            performer=_stub_performer(name="tricot", romaji="tricot"),
            song_title="Title",
            venue_name="Daikanyama UNIT",
            performance_date=date(2026, 4, 25),
            artist_url="https://example.com/tricot",
            venue_url=None,
        )
        self.assertEqual(img.size, VIDEO_SIZE)


class TestRenderVideoClosingSlide(TestCase):
    def test_closing_renders(self) -> None:
        img = render_video_closing_slide(
            closing_text="See you next month",
            channel_url="https://www.youtube.com/@hakkoakkei",
        )
        self.assertEqual(img.size, VIDEO_SIZE)

    def test_closing_handles_long_text(self) -> None:
        img = render_video_closing_slide(
            closing_text="Thanks for tuning in to the April lineup, see you in May",
            channel_url="https://www.youtube.com/@hakkoakkei",
        )
        self.assertEqual(img.size, VIDEO_SIZE)
