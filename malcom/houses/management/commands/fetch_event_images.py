"""Fetch and save event flyer images for PerformanceSchedule records missing them."""

import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandParser
from django.db.models import QuerySet
from houses.models import PerformanceSchedule

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "hakoake-image-fetcher/1.0"
_TIMEOUT = 15
_MIN_IMAGE_DIMENSION = 200

# Maps crawler_class name → callable that produces the detail page URL for a schedule.
_SOURCE_URL_BUILDERS: dict[str, callable] = {
    "AntiknockCrawler": lambda s: f"https://www.antiknock.net/schedule/{s.performance_date.strftime('%Y%m%d')}/",
}


def _backfill_source_urls(qs: QuerySet) -> int:
    """Construct and save source_url for schedules that have a known URL pattern."""
    updated = 0
    for schedule in qs.filter(source_url="").select_related("live_house__website"):
        crawler_class = schedule.live_house.website.crawler_class
        builder = _SOURCE_URL_BUILDERS.get(crawler_class)
        if builder:
            schedule.source_url = builder(schedule)
            schedule.save(update_fields=["source_url"])
            updated += 1
    return updated


def _extract_image_url(html: str, base_url: str) -> str | None:
    """Extract the most prominent image URL from an event detail page.

    Priority: og:image → first large <img> with src.
    """
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(base_url, og["content"])

    for img in soup.find_all("img", src=True):
        src = img["src"]
        if not src or src.startswith("data:"):
            continue
        w = img.get("width", "")
        h = img.get("height", "")
        try:
            if int(w) >= _MIN_IMAGE_DIMENSION or int(h) >= _MIN_IMAGE_DIMENSION:
                return urljoin(base_url, src)
        except (ValueError, TypeError):
            pass

    return None


def _fetch_and_save(schedule: PerformanceSchedule) -> bool:
    """Fetch the event image from schedule.source_url and save it. Returns True on success."""
    url = schedule.source_url
    try:
        resp = _SESSION.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to fetch {url}: {exc}")
        return False

    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    image_url = _extract_image_url(resp.text, base)
    if not image_url:
        logger.debug(f"No image found on {url}")
        return False

    try:
        img_resp = _SESSION.get(image_url, timeout=_TIMEOUT)
        img_resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to download image {image_url}: {exc}")
        return False

    content_type = img_resp.headers.get("Content-Type", "")
    if "svg" in content_type.lower():
        try:
            import cairosvg  # noqa: PLC0415

            content = cairosvg.svg2png(bytestring=img_resp.content)
            ext = "png"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"SVG conversion failed for {image_url}: {exc}")
            return False
    else:
        content = img_resp.content
        ext = image_url.split("?")[0].rsplit(".", 1)[-1] or "jpg"

    filename = f"event_{schedule.pk}.{ext}"
    schedule.event_image.save(filename, ContentFile(content), save=True)
    logger.info(f"Saved event image for schedule {schedule.pk} from {image_url}")
    return True


class Command(BaseCommand):
    help = "Fetch missing event flyer images for PerformanceSchedule records"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch images even if event_image is already set",
        )
        parser.add_argument(
            "--schedule-id",
            type=int,
            help="Fetch image for a single PerformanceSchedule by PK",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum number of schedules to process (0 = no limit)",
        )
        parser.add_argument(
            "--backfill-urls",
            action="store_true",
            help="Construct source_url for schedules with known URL patterns before fetching",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        force = options["force"]
        schedule_id = options.get("schedule_id")
        limit = options["limit"]
        backfill_urls = options["backfill_urls"]

        base_qs = PerformanceSchedule.objects.select_related("live_house__website")
        if schedule_id:
            base_qs = base_qs.filter(pk=schedule_id)
        if not force:
            base_qs = base_qs.filter(event_image="")

        if backfill_urls:
            updated = _backfill_source_urls(base_qs)
            if updated:
                self.stdout.write(f"Backfilled source_url for {updated} schedule(s)")

        qs = base_qs.exclude(source_url="")
        if limit:
            qs = qs[:limit]

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No schedules with source_url to process"))
            return

        self.stdout.write(f"Processing {total} schedule(s)...")
        success = 0

        for schedule in qs:
            result = _fetch_and_save(schedule)
            if result:
                success += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ {schedule}"))
            else:
                self.stdout.write(f"  - {schedule} (no image found)")

        self.stdout.write(f"\nDone — {success}/{total} images fetched")
