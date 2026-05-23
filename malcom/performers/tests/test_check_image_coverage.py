"""Tests for the check_image_coverage management command."""

from __future__ import annotations

import json
from datetime import date
from io import StringIO

from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.test import TestCase
from houses.models import LiveHouse, LiveHouseWebsite, PerformanceSchedule

from performers.management.commands.check_image_coverage import (
    EXIT_BELOW_THRESHOLD,
    _resolve_week_start,
)
from performers.models import Performer


def _make_performer(name: str, *, with_image: bool = False) -> Performer:
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    if with_image:
        performer.performer_image.save(f"{name}.jpg", ContentFile(b"fake"), save=True)
    return performer


def _make_venue() -> LiveHouse:
    website = LiveHouseWebsite.objects.create(url="https://example.com/")
    return LiveHouse.objects.create(
        website=website,
        name="Test Venue",
        name_kana="テスト",
        name_romaji="Test",
        address="addr",
        capacity=100,
        opened_date=date(2000, 1, 1),
    )


class ResolveWeekStartTests(TestCase):
    def test_explicit_week_start_parsed(self) -> None:
        self.assertEqual(_resolve_week_start("2026-06-01"), date(2026, 6, 1))

    def test_invalid_week_start_raises(self) -> None:
        with self.assertRaises(CommandError):
            _resolve_week_start("not-a-date")


class CheckImageCoverageCommandTests(TestCase):
    def setUp(self) -> None:
        self.venue = _make_venue()
        self.week_start = date(2026, 6, 1)

    def _schedule_for(self, performer: Performer, *, with_image: bool = False) -> PerformanceSchedule:
        schedule = PerformanceSchedule.objects.create(
            live_house=self.venue,
            performance_name="Show",
            performance_date=date(2026, 6, 3),
        )
        schedule.performers.add(performer)
        if with_image:
            schedule.event_image.save(f"{performer.name}-flyer.jpg", ContentFile(b"flyer"), save=True)
        return schedule

    def test_text_output_when_above_threshold(self) -> None:
        performer = _make_performer("HasArt", with_image=True)
        self._schedule_for(performer, with_image=True)

        out = StringIO()
        call_command(
            "check_image_coverage",
            "--target-week=2026-06-01",
            "--scope=week",
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("Performers with image: 1/1", output)
        self.assertIn("at or above", output)
        self.assertIn("Schedules with event_image: 1/1", output)

    def test_json_output_below_threshold_exits_non_zero(self) -> None:
        # 2 of 10 performers (20%) have artwork — well below the 70% default.
        for i in range(2):
            self._schedule_for(_make_performer(f"HasArt{i}", with_image=True))
        for i in range(8):
            self._schedule_for(_make_performer(f"Missing{i}"))

        out = StringIO()
        with self.assertRaises(SystemExit) as exit_ctx:
            call_command(
                "check_image_coverage",
                "--target-week=2026-06-01",
                "--scope=week",
                "--format=json",
                stdout=out,
            )

        self.assertEqual(exit_ctx.exception.code, EXIT_BELOW_THRESHOLD)
        payload = json.loads(out.getvalue().splitlines()[-1])
        self.assertTrue(payload["below_threshold"])
        self.assertEqual(payload["scope"], "week")
        self.assertEqual(payload["performer_total"], 10)
        self.assertEqual(payload["performers_with_image"], 2)
        self.assertIn("performers_without_image", payload)
        self.assertEqual(len(payload["performers_without_image"]), 8)

    def test_scope_all_covers_every_performer(self) -> None:
        _make_performer("WithArt", with_image=True)
        _make_performer("NoArt")

        out = StringIO()
        call_command(
            "check_image_coverage",
            "--target-week=2026-06-01",
            "--scope=all",
            "--threshold=0.0",
            "--format=json",
            stdout=out,
        )

        payload = json.loads(out.getvalue().splitlines()[-1])
        self.assertEqual(payload["performer_total"], 2)
        self.assertEqual(payload["performers_with_image"], 1)

    def test_zero_performers_does_not_exit_non_zero(self) -> None:
        out = StringIO()
        call_command(
            "check_image_coverage",
            "--target-week=2026-06-01",
            "--scope=week",
            stdout=out,
        )
        self.assertIn("Performers with image: 0/0", out.getvalue())
