"""Report performer / event-image coverage and warn when below threshold.

Designed to run from cron so silent scraper failures (TheAudioDB,
MusicBrainz, event-flyer crawlers) surface before they cause carousel
posts to fall back to the default background. Exits non-zero with code
``EXIT_BELOW_THRESHOLD`` when the performer coverage ratio is below the
configured threshold so cron alerting (mail-on-failure, etc.) fires.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta

from commons.image_coverage import (
    DEFAULT_PERFORMER_COVERAGE_THRESHOLD,
    build_image_coverage_report,
    log_image_coverage_report,
)
from django.core.management.base import BaseCommand, CommandError, CommandParser

from performers.models import Performer

EXIT_OK = 0
EXIT_BELOW_THRESHOLD = 2

DEFAULT_SCOPE = "week"
SCOPE_CHOICES = (DEFAULT_SCOPE, "all")


def _resolve_week_start(target_week: str | None) -> date:
    """Return the Monday for the target week, defaulting to the upcoming Monday."""
    if target_week:
        try:
            return datetime.strptime(target_week, "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError as exc:
            raise CommandError(f"--target-week must be YYYY-MM-DD, got {target_week!r}") from exc
    today = date.today()  # noqa: DTZ011
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    return today + timedelta(days=days_until_monday)


class Command(BaseCommand):
    help = (
        "Report performer image coverage and event_image coverage for the target week. "
        "Exits with status 2 when performer coverage is below --threshold."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--target-week",
            type=str,
            default=None,
            help="Monday (YYYY-MM-DD) of the target week. Default: upcoming Monday.",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=DEFAULT_PERFORMER_COVERAGE_THRESHOLD,
            help=f"Performer coverage threshold 0-1 (default: {DEFAULT_PERFORMER_COVERAGE_THRESHOLD}).",
        )
        parser.add_argument(
            "--scope",
            choices=SCOPE_CHOICES,
            default=DEFAULT_SCOPE,
            help="week: performers scheduled in the target week. all: every Performer in the DB.",
        )
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format (default: text).",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        threshold: float = options["threshold"]
        scope: str = options["scope"]
        output_format: str = options["format"]
        week_start = _resolve_week_start(options["target_week"])
        week_end = week_start + timedelta(days=7)

        if scope == "week":
            performers = list(
                Performer.objects.filter(
                    performance_schedules__performance_date__gte=week_start,
                    performance_schedules__performance_date__lt=week_end,
                ).distinct()
            )
        else:
            performers = list(Performer.objects.all())

        report = build_image_coverage_report(performers, week_start, threshold=threshold)
        log_image_coverage_report(report, context=f"check_image_coverage:{scope}")

        if output_format == "json":
            payload = report.to_log_payload(context=f"check_image_coverage:{scope}")
            payload["scope"] = scope
            payload["performers_without_image"] = report.performers_without_image
            self.stdout.write(json.dumps(payload, sort_keys=True))
        else:
            self._write_text_report(report, scope, week_start)

        if report.below_threshold:
            sys.exit(EXIT_BELOW_THRESHOLD)

    def _write_text_report(self, report, scope: str, week_start: date) -> None:  # noqa: ANN001
        self.stdout.write(f"Week starting: {week_start}")
        self.stdout.write(f"Scope: {scope}")
        self.stdout.write(
            f"Performers with image: {report.performers_with_image}/{report.performer_total} "
            f"({report.performer_coverage_ratio:.0%})"
        )
        self.stdout.write(
            f"Schedules with event_image: {report.schedules_with_event_image}/{report.schedule_total} "
            f"({report.schedule_coverage_ratio:.0%})"
        )
        if report.performers_without_image:
            self.stdout.write("Performers missing artwork:")
            for name in report.performers_without_image:
                self.stdout.write(f"  - {name}")
        if report.below_threshold:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠ Performer coverage {report.performer_coverage_ratio:.0%} below threshold {report.threshold:.0%}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Performer coverage {report.performer_coverage_ratio:.0%} at or above "
                    f"threshold {report.threshold:.0%}"
                )
            )
