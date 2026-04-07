"""Post a weekly playlist announcement as a carousel.

Carousel structure:
  Slide 1      — cover: numbered performer list for the week
  Slides 2k    — per-performer: event flyer image (or performer card fallback)
  Slides 2k+1  — per-performer: QR code slide with metadata

Usage:
    uv run python manage.py post_weekly_playlist
    uv run python manage.py post_weekly_playlist --playlist-id 42
    uv run python manage.py post_weekly_playlist --dry-run
    uv run python manage.py post_weekly_playlist --platform instagram
"""

from __future__ import annotations

import logging
from datetime import timedelta

from commons.instagram_images import (
    INSTAGRAM_HASHTAGS,
    _resize_to_square,
    generate_performer_card,
    generate_playlist_cover,
    generate_qr_slide,
)
from commons.instagram_post import build_caption, post_carousel
from commons.instagram_utils import get_instagram_token
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from houses.formatting import build_lineup_lines, build_playlist_description
from houses.models import PerformanceSchedule, WeeklyPlaylist, WeeklyPlaylistEntry

logger = logging.getLogger(__name__)

MAX_CAROUSEL_SLIDES = 10


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

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, PLR0912, PLR0915
        playlist_id: int | None = options["playlist_id"]
        platform: str = options["platform"]
        dry_run: bool = options["dry_run"]

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

        entries = list(
            WeeklyPlaylistEntry.objects.filter(playlist=playlist).order_by("position").select_related("song__performer")
        )
        if not entries:
            self.stderr.write(self.style.ERROR("Playlist has no entries"))
            return

        max_performers = (MAX_CAROUSEL_SLIDES - 1) // 2
        if len(entries) > max_performers:
            logger.warning(
                "Playlist has %d entries; truncating to %d to stay within %d-slide carousel limit",
                len(entries),
                max_performers,
                MAX_CAROUSEL_SLIDES,
            )
            entries = entries[:max_performers]

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

        # --- Cover slide ---
        cover_entries = [(e.position, e.song.performer.name) for e in entries]
        title = f"HAKKO-AKKEI WEEK {week_start.strftime('%Y-%m-%d')} TOKYO Playlist"
        cover_bytes = generate_playlist_cover(title, week_label, cover_entries)
        self.stdout.write(f"Generated cover image ({len(cover_bytes):,} bytes)")
        images: list[tuple[bytes, str]] = [(cover_bytes, "cover.jpg")]

        # --- Per-performer slides ---
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

            # Flyer slide
            if schedule and schedule.event_image and schedule.event_image.name:
                try:
                    with schedule.event_image.open("rb") as f:
                        raw = f.read()
                    flyer_bytes = _resize_to_square(raw, 1080)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Could not load event_image for {performer.name}: {exc}; using performer card")
                    all_schedules = list(
                        PerformanceSchedule.objects.filter(
                            performers=performer,
                            performance_date__gte=week_start,
                            performance_date__lt=week_end,
                        ).select_related("live_house")
                    )
                    flyer_bytes = generate_performer_card(performer, pos, all_schedules)
            else:
                all_schedules = list(
                    PerformanceSchedule.objects.filter(
                        performers=performer,
                        performance_date__gte=week_start,
                        performance_date__lt=week_end,
                    ).select_related("live_house")
                )
                flyer_bytes = generate_performer_card(performer, pos, all_schedules)

            flyer_filename = f"flyer_{pos:02d}_{performer.name[:20].replace(' ', '_')}.jpg"
            images.append((flyer_bytes, flyer_filename))
            self.stdout.write(f"Generated flyer for {performer.name} ({len(flyer_bytes):,} bytes)")

            # QR code slide
            qr_url = _get_qr_url(schedule)
            venue_name = schedule.live_house.name if schedule else ""
            event_name = schedule.performance_name if schedule else ""
            event_date = schedule.performance_date if schedule else week_start

            qr_bytes = generate_qr_slide(
                url=qr_url,
                position=pos,
                performer_name=performer.name,
                venue_name=venue_name,
                event_name=event_name,
                event_date=event_date,
            )
            qr_filename = f"qr_{pos:02d}_{performer.name[:20].replace(' ', '_')}.jpg"
            images.append((qr_bytes, qr_filename))
            self.stdout.write(f"Generated QR slide for {performer.name} ({len(qr_bytes):,} bytes)")

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
        self.stdout.write(self.style.SUCCESS(f"Posted to {platform}: post_id={post_id}"))
