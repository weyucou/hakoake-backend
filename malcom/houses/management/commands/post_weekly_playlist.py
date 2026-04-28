"""Post a weekly playlist announcement as a carousel.

Carousel structure:
  Slide 1    — cover: numbered performer list for the week
  Slides 2-N — per-performer: combined flyer + QR code overlay

With 1 cover + 1 slide per performer, up to 9 performers fit in
Instagram's 10-slide carousel limit.

Usage:
    uv run python manage.py post_weekly_playlist
    uv run python manage.py post_weekly_playlist --playlist-id 42
    uv run python manage.py post_weekly_playlist --dry-run
    uv run python manage.py post_weekly_playlist --platform instagram
"""

from __future__ import annotations

import io
import logging
from datetime import timedelta

from commons.instagram_images import (
    INSTAGRAM_HASHTAGS,
    _resize_to_square,
    generate_combined_flyer_qr_slide,
    generate_performer_card,
    generate_playlist_cover,
)
from commons.instagram_post import build_caption, post_carousel
from commons.instagram_utils import get_instagram_token
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from houses.formatting import build_lineup_lines, build_playlist_description
from houses.models import PerformanceSchedule, WeeklyPlaylist, WeeklyPlaylistEntry
from PIL import Image

logger = logging.getLogger(__name__)

MAX_CAROUSEL_SLIDES = 10
_MIN_FLYER_DIMENSION = 200
_BLACK_THRESHOLD = 10  # per-channel sum below this → effectively black
_WHITE_THRESHOLD = 740  # per-channel sum above this → effectively white (255*3=765)


def _is_valid_flyer(raw: bytes) -> bool:
    """Return False if the image is too small or is uniformly black/white (likely a placeholder icon)."""
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001
        return False
    if img.width < _MIN_FLYER_DIMENSION or img.height < _MIN_FLYER_DIMENSION:
        return False
    # Sample a grid of pixels; reject if all are near-black or all are near-white.
    pixels = [
        img.getpixel((x, y))
        for x in range(0, img.width, img.width // 4 + 1)
        for y in range(0, img.height, img.height // 4 + 1)
    ]
    channel_sums = [r + g + b for r, g, b in pixels]
    all_black = all(s <= _BLACK_THRESHOLD for s in channel_sums)
    all_white = all(s >= _WHITE_THRESHOLD for s in channel_sums)
    return not all_black and not all_white


def _post_instagram(
    user_id: str,
    images: list[tuple[bytes, str]],
    caption: str,
    cert_file: object,
    key_file: object,
) -> str:
    token_cache = cert_file.parent / "instagram_token.json"
    token = get_instagram_token(cert_file, key_file, token_cache)
    return post_carousel(user_id, token.access_token, images, caption)


PLATFORM_HANDLERS = {
    "instagram": _post_instagram,
}

VALID_POST_PLATFORMS = list(PLATFORM_HANDLERS)


def _get_qr_url(schedule) -> str:  # noqa: ANN001
    """Return the ticket or venue schedule URL for the QR code slide."""
    if not schedule:
        return ""
    try:
        if schedule.ticket_purchase_info.ticket_url:
            return str(schedule.ticket_purchase_info.ticket_url)
    except Exception:  # noqa: BLE001, S110
        pass
    return schedule.live_house.website.schedule_url or ""


class Command(BaseCommand):
    help = "Post a weekly playlist announcement as a multi-image carousel"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--playlist-id",
            type=int,
            default=None,
            help="WeeklyPlaylist pk; omit to use the latest by date",
        )
        parser.add_argument(
            "--platform",
            choices=VALID_POST_PLATFORMS,
            default="instagram",
            help="Posting target (default: instagram)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log images and caption without posting",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Bypass the instagram_post_id guard and re-post even if already posted",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, C901, PLR0912, PLR0915
        playlist_id: int | None = options["playlist_id"]
        platform: str = options["platform"]
        dry_run: bool = options["dry_run"]
        force: bool = options["force"]

        # --- Resolve playlist ---
        if playlist_id:
            try:
                playlist = WeeklyPlaylist.objects.get(id=playlist_id)
            except WeeklyPlaylist.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"WeeklyPlaylist id={playlist_id} not found"))
                return
        else:
            playlist = WeeklyPlaylist.objects.order_by("-date").first()
            if not playlist:
                self.stderr.write(self.style.ERROR("No WeeklyPlaylist found"))
                return

        # Idempotency guard — skip when IG post already exists (unless forced or a dry-run).
        if playlist.instagram_post_id and not dry_run and not force:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Playlist {playlist.id} already posted to instagram "
                    f"(post_id={playlist.instagram_post_id}); skipping. Pass --force to re-post."
                )
            )
            return

        all_entries = list(
            WeeklyPlaylistEntry.objects.filter(playlist=playlist).order_by("position").select_related("song__performer")
        )
        if not all_entries:
            self.stderr.write(self.style.ERROR("Playlist has no entries"))
            return

        # 1 cover + 1 combined slide per performer = max (MAX_CAROUSEL_SLIDES - 1) performers
        max_performers = MAX_CAROUSEL_SLIDES - 1
        entries = all_entries[:max_performers]
        if len(all_entries) > max_performers:
            logger.warning(
                "Playlist has %d entries; only first %d get slides (cover lists all) "
                "to stay within %d-slide carousel limit",
                len(all_entries),
                max_performers,
                MAX_CAROUSEL_SLIDES,
            )

        week_start = playlist.date
        week_end = week_start + timedelta(days=7)
        week_label = f"Week of {week_start.strftime('%Y-%m-%d')}"

        self.stdout.write(f"Playlist: {playlist.id} — {week_label}")
        self.stdout.write(f"Entries: {len(entries)}")

        # --- Build caption ---
        performer_song_pairs = [(e.song.performer, e.song) for e in entries]
        lineup_lines = build_lineup_lines(performer_song_pairs, week_start, week_end)
        lineup_str = "\n".join(lineup_lines)
        period_text = f"week of {week_start.strftime('%Y-%m-%d')}"
        description = build_playlist_description(period_text, lineup_str)
        playlist_url = (
            playlist.youtube_playlist_url or f"https://www.youtube.com/playlist?list={playlist.youtube_playlist_id}"
        )
        caption = build_caption(description, playlist_url, INSTAGRAM_HASHTAGS)

        if dry_run:
            self.stdout.write("\n--- CAPTION ---")
            self.stdout.write(caption)
            self.stdout.write(f"\nCaption length: {len(caption)} chars")

        # --- Cover slide (lists every entry, not just the truncated set) ---
        cover_entries = [(e.position, e.song.performer.name) for e in all_entries]
        title = f"HAKKO-AKKEI WEEK {week_start.strftime('%Y-%m-%d')} TOKYO Playlist"
        cover_bytes = generate_playlist_cover(title, week_label, cover_entries)
        self.stdout.write(f"Generated cover image ({len(cover_bytes):,} bytes)")
        images: list[tuple[bytes, str]] = [(cover_bytes, "cover.jpg")]

        # --- Per-performer combined slides (flyer + QR overlay) ---
        for entry in entries:
            performer = entry.song.performer
            pos = entry.position

            schedule = (
                PerformanceSchedule.objects.filter(
                    performers=performer,
                    performance_date__gte=week_start,
                    performance_date__lt=week_end,
                )
                .select_related("live_house")
                .order_by("performance_date")
                .first()
            )

            # Get flyer image bytes: event image (if valid) → performer card with insta-background fallback.
            flyer_bytes = None
            if schedule and schedule.event_image and schedule.event_image.name:
                raw = None
                try:
                    with schedule.event_image.open("rb") as f:
                        raw = f.read()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Could not read event_image for {performer.name}: {exc}")
                if raw and _is_valid_flyer(raw):
                    flyer_bytes = _resize_to_square(raw, 1080)
                elif raw is not None:
                    logger.warning(
                        "event_image for %s rejected (too small or uniform colour): %s; using performer card",
                        performer.name,
                        schedule.event_image.name,
                    )
            if flyer_bytes is None:
                all_schedules = list(
                    PerformanceSchedule.objects.filter(
                        performers=performer,
                        performance_date__gte=week_start,
                        performance_date__lt=week_end,
                    ).select_related("live_house")
                )
                flyer_bytes = generate_performer_card(performer, pos, all_schedules)

            # Combine flyer + QR into a single slide
            qr_url = _get_qr_url(schedule)
            venue_name = schedule.live_house.name if schedule else ""
            event_name = schedule.performance_name if schedule else ""
            event_date = schedule.performance_date if schedule else week_start

            combined_bytes = generate_combined_flyer_qr_slide(
                flyer_bytes=flyer_bytes,
                url=qr_url,
                position=pos,
                performer_name=performer.name,
                venue_name=venue_name,
                event_name=event_name,
                event_date=event_date,
            )
            filename = f"slide_{pos:02d}_{performer.name[:20].replace(' ', '_')}.jpg"
            images.append((combined_bytes, filename))
            self.stdout.write(f"Generated combined slide for {performer.name} ({len(combined_bytes):,} bytes)")

        self.stdout.write(f"Total slides: {len(images)}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nDry run complete — {len(images)} images generated, not posted"))
            return

        # --- Post ---
        if not settings.INSTAGRAM_USER_ID:
            self.stderr.write(self.style.ERROR("INSTAGRAM_USER_ID not set in .env"))
            return

        cert_file = settings.OAUTH_LOCALHOST_CERT
        key_file = settings.OAUTH_LOCALHOST_KEY
        handler = PLATFORM_HANDLERS[platform]
        post_id = handler(settings.INSTAGRAM_USER_ID, images, caption, cert_file, key_file)
        # Persist immediately so a later crash cannot cause a re-post.
        if platform == "instagram":
            playlist.instagram_post_id = post_id
            playlist.save(update_fields=["instagram_post_id"])
        self.stdout.write(self.style.SUCCESS(f"Posted to {platform}: post_id={post_id}"))
