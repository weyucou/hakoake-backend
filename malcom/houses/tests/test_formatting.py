"""Tests for houses.formatting — lineup and playlist description builders."""

from __future__ import annotations

from datetime import date

from django.test import TestCase
from performers.models import Performer, PerformerSong

from houses.formatting import build_lineup_lines, build_playlist_description
from houses.models import LiveHouse, LiveHouseWebsite, PerformanceSchedule


def _make_performer(name: str = "TestBand") -> Performer:
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    return performer


def _make_song(performer: Performer, video_id: str = "vid123") -> PerformerSong:
    return PerformerSong.objects.create(
        performer=performer,
        title=f"{performer.name} Song",
        youtube_video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        youtube_view_count=1000,
        youtube_duration_seconds=180,
    )


class TestBuildLineupLines(TestCase):
    """WHEN a lineup line is generated, THEN it includes the abbreviated weekday for the performance date."""

    def setUp(self) -> None:
        self.website = LiveHouseWebsite.objects.create(url="https://example.com", crawler_class="test_crawler")
        self.live_house = LiveHouse.objects.create(
            website=self.website,
            name="Test Venue",
            name_kana="テストベニュー",
            name_romaji="tesuto benyuu",
            address="Tokyo",
            capacity=100,
            opened_date=date(2020, 1, 1),
        )

    def _schedule(self, performer: Performer, performance_date: date) -> PerformanceSchedule:
        schedule = PerformanceSchedule.objects.create(
            live_house=self.live_house,
            performance_name="Night",
            performance_date=performance_date,
        )
        schedule.performers.add(performer)
        return schedule

    def test_line_contains_abbreviated_weekday(self) -> None:
        """2026-03-30 is a Monday — line must contain '(Mon)'."""
        performer = _make_performer("MonBand")
        song = _make_song(performer)
        self._schedule(performer, date(2026, 3, 30))

        lines = build_lineup_lines([(performer, song)], date(2026, 3, 30), date(2026, 4, 6))

        self.assertEqual(len(lines), 1)
        self.assertIn("2026-03-30 (Mon)", lines[0])
        self.assertIn("MonBand", lines[0])
        self.assertIn("Test Venue", lines[0])

    def test_line_format_for_each_weekday(self) -> None:
        """Each weekday (Mon..Sun) in a week must appear as its abbreviation."""
        expected = {
            date(2026, 3, 30): "Mon",
            date(2026, 3, 31): "Tue",
            date(2026, 4, 1): "Wed",
            date(2026, 4, 2): "Thu",
            date(2026, 4, 3): "Fri",
            date(2026, 4, 4): "Sat",
            date(2026, 4, 5): "Sun",
        }
        for performance_date, abbr in expected.items():
            performer = _make_performer(f"Band-{abbr}")
            song = _make_song(performer, video_id=f"vid-{abbr}")
            self._schedule(performer, performance_date)

            lines = build_lineup_lines([(performer, song)], date(2026, 3, 30), date(2026, 4, 6))

            self.assertEqual(len(lines), 1)
            self.assertIn(f"{performance_date.isoformat()} ({abbr})", lines[0])


class TestBuildPlaylistDescription(TestCase):
    """WHEN a playlist description is built from lineup lines, THEN weekday abbreviations are preserved."""

    def test_description_contains_weekday_abbreviation(self) -> None:
        lineup_str = "1. 2026-03-30 (Mon) BandA @ Test Venue"
        description = build_playlist_description("week of 2026-03-30", lineup_str)
        self.assertIn("(Mon)", description)
        self.assertIn("2026-03-30", description)
