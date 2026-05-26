"""Tests for the commons.image_coverage module."""

from __future__ import annotations

from datetime import date

from django.core.files.base import ContentFile
from django.test import TestCase
from houses.models import LiveHouse, LiveHouseWebsite, PerformanceSchedule
from performers.models import Performer

from commons.image_coverage import (
    DEFAULT_PERFORMER_COVERAGE_THRESHOLD,
    ImageCoverageReport,
    build_image_coverage_report,
    log_image_coverage_report,
    performer_has_image,
)


def _make_performer(name: str, *, with_image: bool = False) -> Performer:
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    if with_image:
        performer.performer_image.save(f"{name}.jpg", ContentFile(b"fake"), save=True)
    return performer


def _make_schedule(
    live_house: LiveHouse,
    performance_date: date,
    performer: Performer,
    *,
    with_image: bool = False,
) -> PerformanceSchedule:
    schedule = PerformanceSchedule.objects.create(
        live_house=live_house,
        performance_name="Test Show",
        performance_date=performance_date,
    )
    schedule.performers.add(performer)
    if with_image:
        schedule.event_image.save(f"{performer.name}-flyer.jpg", ContentFile(b"flyer"), save=True)
    return schedule


class PerformerHasImageTests(TestCase):
    def test_returns_true_when_any_image_set(self) -> None:
        performer = _make_performer("WithImage", with_image=True)
        self.assertTrue(performer_has_image(performer))

    def test_returns_false_when_all_images_blank(self) -> None:
        performer = _make_performer("NoImage")
        self.assertFalse(performer_has_image(performer))


class BuildImageCoverageReportTests(TestCase):
    def setUp(self) -> None:
        self.week_start = date(2026, 6, 1)
        self.website = LiveHouseWebsite.objects.create(url="https://example.com/")
        self.live_house = LiveHouse.objects.create(
            website=self.website,
            name="Test Venue",
            name_kana="テスト",
            name_romaji="Test",
            address="addr",
            capacity=100,
            opened_date=date(2000, 1, 1),
        )

    def test_empty_performer_list_returns_full_coverage_ratio(self) -> None:
        report = build_image_coverage_report([], self.week_start)
        self.assertEqual(report.performer_total, 0)
        self.assertEqual(report.performer_coverage_ratio, 1.0)
        self.assertFalse(report.below_threshold)
        self.assertEqual(report.schedule_total, 0)
        self.assertEqual(report.schedule_coverage_ratio, 1.0)

    def test_counts_performers_with_and_without_images(self) -> None:
        with_image = _make_performer("HasArt", with_image=True)
        without_image = _make_performer("NoArt")

        report = build_image_coverage_report([with_image, without_image], self.week_start)

        self.assertEqual(report.performer_total, 2)
        self.assertEqual(report.performers_with_image, 1)
        self.assertEqual(report.performers_without_image, ["NoArt"])
        self.assertAlmostEqual(report.performer_coverage_ratio, 0.5)

    def test_below_threshold_triggers_when_ratio_under_default(self) -> None:
        performers = [_make_performer(f"NoArt{i}") for i in range(8)]
        performers += [_make_performer(f"HasArt{i}", with_image=True) for i in range(2)]

        report = build_image_coverage_report(performers, self.week_start)

        self.assertLess(report.performer_coverage_ratio, DEFAULT_PERFORMER_COVERAGE_THRESHOLD)
        self.assertTrue(report.below_threshold)

    def test_above_threshold_does_not_trigger(self) -> None:
        performers = [_make_performer(f"HasArt{i}", with_image=True) for i in range(8)]
        performers += [_make_performer(f"NoArt{i}") for i in range(2)]

        report = build_image_coverage_report(performers, self.week_start)

        self.assertGreaterEqual(report.performer_coverage_ratio, DEFAULT_PERFORMER_COVERAGE_THRESHOLD)
        self.assertFalse(report.below_threshold)

    def test_counts_schedules_within_target_week(self) -> None:
        performer = _make_performer("InWeek", with_image=True)
        _make_schedule(self.live_house, date(2026, 6, 3), performer, with_image=True)
        _make_schedule(self.live_house, date(2026, 6, 6), performer)
        # Outside the target week — must not be counted.
        _make_schedule(self.live_house, date(2026, 6, 12), performer, with_image=True)

        report = build_image_coverage_report([performer], self.week_start)

        self.assertEqual(report.schedule_total, 2)
        self.assertEqual(report.schedules_with_event_image, 1)
        self.assertAlmostEqual(report.schedule_coverage_ratio, 0.5)

    def test_custom_threshold_overrides_default(self) -> None:
        performer = _make_performer("HasArt", with_image=True)

        report = build_image_coverage_report([performer], self.week_start, threshold=1.0)

        self.assertEqual(report.threshold, 1.0)
        self.assertFalse(report.below_threshold)


class LogImageCoverageReportTests(TestCase):
    def test_warning_logged_when_below_threshold(self) -> None:
        report = ImageCoverageReport(
            week_start=date(2026, 6, 1),
            performer_total=10,
            performers_with_image=3,
            performers_without_image=[f"Missing{i}" for i in range(7)],
            schedule_total=4,
            schedules_with_event_image=1,
            threshold=0.7,
        )

        with self.assertLogs("commons.image_coverage", level="WARNING") as captured:
            log_image_coverage_report(report, context="unit-test")

        joined = "\n".join(captured.output)
        self.assertIn("image_coverage_below_threshold", joined)
        self.assertIn("Missing0", joined)

    def test_info_logged_when_at_or_above_threshold(self) -> None:
        report = ImageCoverageReport(
            week_start=date(2026, 6, 1),
            performer_total=10,
            performers_with_image=9,
            performers_without_image=["Missing"],
            schedule_total=4,
            schedules_with_event_image=4,
            threshold=0.7,
        )

        with self.assertLogs("commons.image_coverage", level="INFO") as captured:
            log_image_coverage_report(report, context="unit-test")

        joined = "\n".join(captured.output)
        self.assertIn("image_coverage_summary", joined)
        self.assertNotIn("image_coverage_below_threshold", joined)


class ImageCoverageReportLogPayloadTests(TestCase):
    def test_payload_includes_threshold_and_ratio(self) -> None:
        report = ImageCoverageReport(
            week_start=date(2026, 6, 1),
            performer_total=4,
            performers_with_image=3,
            performers_without_image=["Missing"],
            schedule_total=2,
            schedules_with_event_image=1,
            threshold=0.7,
        )

        payload = report.to_log_payload(context="ctx")

        self.assertEqual(payload["context"], "ctx")
        self.assertEqual(payload["performer_total"], 4)
        self.assertEqual(payload["performers_with_image"], 3)
        self.assertEqual(payload["performers_without_image_count"], 1)
        self.assertEqual(payload["performer_coverage_ratio"], 0.75)
        self.assertEqual(payload["schedule_coverage_ratio"], 0.5)
        self.assertEqual(payload["threshold"], 0.7)
        self.assertFalse(payload["below_threshold"])
