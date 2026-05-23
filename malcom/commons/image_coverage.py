"""Image coverage metrics for performer / event scraper health.

Surface silent scraper failures (TheAudioDB/MusicBrainz for performer art,
crawler-driven event flyers for ``PerformanceSchedule.event_image``) by
counting how many performers in the upcoming week have artwork and how
many schedules carry a flyer. Used by ``post_weekly_playlist`` for a
pre-post summary and by ``check_image_coverage`` as a stand-alone health
check that can run from cron.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from performers.models import Performer

logger = logging.getLogger(__name__)

DEFAULT_PERFORMER_COVERAGE_THRESHOLD = 0.7

PERFORMER_IMAGE_FIELDS: tuple[str, ...] = (
    "performer_image",
    "logo_image",
    "fanart_image",
    "banner_image",
)


@dataclass(frozen=True)
class ImageCoverageReport:
    """Snapshot of performer / event-image coverage for a target week."""

    week_start: date
    performer_total: int
    performers_with_image: int
    performers_without_image: list[str] = field(default_factory=list)
    schedule_total: int = 0
    schedules_with_event_image: int = 0
    threshold: float = DEFAULT_PERFORMER_COVERAGE_THRESHOLD

    @property
    def performer_coverage_ratio(self) -> float:
        if not self.performer_total:
            return 1.0
        return self.performers_with_image / self.performer_total

    @property
    def schedule_coverage_ratio(self) -> float:
        if not self.schedule_total:
            return 1.0
        return self.schedules_with_event_image / self.schedule_total

    @property
    def below_threshold(self) -> bool:
        return self.performer_total > 0 and self.performer_coverage_ratio < self.threshold

    def to_log_payload(self, *, context: str) -> dict:
        return {
            "event": "image_coverage_summary",
            "context": context,
            "week_start": self.week_start.isoformat(),
            "performer_total": self.performer_total,
            "performers_with_image": self.performers_with_image,
            "performers_without_image_count": len(self.performers_without_image),
            "performer_coverage_ratio": round(self.performer_coverage_ratio, 3),
            "schedule_total": self.schedule_total,
            "schedules_with_event_image": self.schedules_with_event_image,
            "schedule_coverage_ratio": round(self.schedule_coverage_ratio, 3),
            "threshold": self.threshold,
            "below_threshold": self.below_threshold,
        }


def performer_has_image(performer: Performer) -> bool:
    """Return True if the performer has at least one image field populated."""
    return any(getattr(performer, field_name) for field_name in PERFORMER_IMAGE_FIELDS)


def build_image_coverage_report(
    performers: Iterable[Performer],
    week_start: date,
    *,
    threshold: float = DEFAULT_PERFORMER_COVERAGE_THRESHOLD,
) -> ImageCoverageReport:
    """Count performer and schedule image coverage for the target week.

    Schedules are restricted to those between ``week_start`` and
    ``week_start + 7 days`` that include at least one of the supplied
    performers, matching what ``post_weekly_playlist`` actually surfaces.
    """
    from houses.models import PerformanceSchedule  # noqa: PLC0415 — avoid app-ready import cycle

    performer_list = list(performers)
    performer_total = len(performer_list)
    with_image = [p for p in performer_list if performer_has_image(p)]
    without_image: list[str] = [str(p.name) for p in performer_list if not performer_has_image(p)]

    schedule_total = 0
    schedules_with_event_image = 0
    if performer_list:
        week_end = week_start + timedelta(days=7)
        schedule_qs = PerformanceSchedule.objects.filter(
            performers__in=performer_list,
            performance_date__gte=week_start,
            performance_date__lt=week_end,
        ).distinct()
        schedule_total = schedule_qs.count()
        schedules_with_event_image = schedule_qs.exclude(event_image="").exclude(event_image__isnull=True).count()

    return ImageCoverageReport(
        week_start=week_start,
        performer_total=performer_total,
        performers_with_image=len(with_image),
        performers_without_image=without_image,
        schedule_total=schedule_total,
        schedules_with_event_image=schedules_with_event_image,
        threshold=threshold,
    )


def log_image_coverage_report(report: ImageCoverageReport, *, context: str) -> None:
    """Emit a structured INFO (or WARNING when below threshold) log line."""
    payload = report.to_log_payload(context=context)
    if report.below_threshold:
        logger.warning(
            "image_coverage_below_threshold payload=%s missing=%s",
            payload,
            report.performers_without_image,
        )
    else:
        logger.info("image_coverage_summary payload=%s", payload)
