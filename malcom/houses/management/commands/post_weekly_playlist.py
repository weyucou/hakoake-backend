"""Post a weekly playlist announcement as a carousel.

Carousel structure:
  Slide 1      — cover: numbered performer list for the week
  Slides 2k    — per-performer: event flyer image (or performer card fallback)
  Slides 2k+1  — per-performer: QR code slide with metadata

Usage:
    uv run python manage.py post_weekly_playlist
    uv run python manage.py post_weekly_playlist --playlist-id 42
    uv run python manage.py post_weekly_playlist --dry-run
    uv run python manage.py post_weekly_playlist --platform instagram --max-performers 3
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
    token_cache = cert_file.parent / "instagram_token.pickle"
    token = get_instagram_token(cert_file, key_file, token_cache)
    return post_carousel(user_id, token.access_token, images, caption)


PLATFORM_HANDLERS = {
    "instagram": _post_instagram,
}


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
            choices=list(PLATFORM_HANDLERS),
            default="instagram",
            help="Posting target (default: instagram)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log images and caption without posting",
        )
        parser.add_argument(
            "--base-url",
            default="https://hakoake.com",
            help="Base URL for QR code links (default: https://hakoake.com)",
        )
        parser.add_argument(
            "--max-performers",
            type=int,
            default=4,
            help="Max performers to include; controls slide count (default: 4)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, PLR0912, PLR0915
        playlist_id: int | None = options["playlist_id"]
        platform: str = options["platform"]
        dry_run: bool = options["dry_run"]
        base_url: str = options["base_url"].rstrip("/")
        max_performers: int = options["max_performers"]

        # Validate slide count before doing any work
        total_slides = 1 + max_performers * 2
        if total_slides > MAX_CAROUSEL_SLIDES:
            self.stderr.write(
                self.style.ERROR(
                    f"--max-performers {max_performers} would produce {total_slides} slides "
                    f"(limit is {MAX_CAROUSEL_SLIDES}). "
                    f"Lower --max-performers to {(MAX_CAROUSEL_SLIDES - 1) // 2} or fewer."
                )
            )
            return

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

        week_start = playlist.date
        week_end = week_start + timedelta(days=7)
        week_label = f"Week of {week_start.strftime('%Y-%m-%d')}"

        self.stdout.write(f"Playlist: {playlist.id} — {week_label}")
        self.stdout.write(f"Entries: {len(entries)}, max performers: {max_performers}")

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
        for entry in entries[:max_performers]:
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
            qr_url = f"{base_url}/performer/{performer.id}/"
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
