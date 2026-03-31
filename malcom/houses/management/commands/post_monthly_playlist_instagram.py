"""Post a monthly playlist announcement to Instagram as a carousel.

Carousel structure:
  Slide 1  — cover: numbered performer list for the month
  Slides 2+ — one card per performer: photo + venue/event details

Usage:
    uv run python manage.py post_monthly_playlist_instagram <target_month>
    uv run python manage.py post_monthly_playlist_instagram <target_month> --dry-run

    <target_month> format: YYYY-MM  (e.g. 2026-03)
"""

from __future__ import annotations

import logging

from commons.functions import get_month_end, parse_month
from commons.instagram_images import INSTAGRAM_HASHTAGS, generate_performer_card, generate_playlist_cover
from commons.instagram_post import build_caption, post_carousel
from commons.instagram_utils import get_instagram_token
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from houses.formatting import build_lineup_lines, build_playlist_description
from houses.models import MonthlyPlaylist, MonthlyPlaylistEntry, PerformanceSchedule

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Post a monthly playlist announcement to Instagram as a multi-image carousel"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("target_month", type=str, help="Target month in YYYY-MM format")
        parser.add_argument("--dry-run", action="store_true", help="Log images and caption without posting")

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, PLR0915
        target_month_str: str = options["target_month"]
        dry_run: bool = options["dry_run"]

        try:
            target_date = parse_month(target_month_str)
        except (ValueError, TypeError) as exc:
            self.stderr.write(self.style.ERROR(f"Invalid target_month: {exc}"))
            return

        try:
            playlist = MonthlyPlaylist.objects.get(date=target_date)
        except MonthlyPlaylist.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"MonthlyPlaylist not found for {target_date.strftime('%Y-%m')}"))
            return

        entries = list(
            MonthlyPlaylistEntry.objects.filter(playlist=playlist)
            .order_by("position")
            .select_related("song__performer")
        )
        if not entries:
            self.stderr.write(self.style.ERROR("Playlist has no entries"))
            return

        month_start = playlist.date
        month_end = get_month_end(month_start)
        month_label = month_start.strftime("%B %Y")

        # --- Build caption from playlist description ---
        performer_song_pairs = [(e.song.performer, e.song) for e in entries]
        lineup_lines = build_lineup_lines(performer_song_pairs, month_start, month_end)
        lineup_str = "\n".join(lineup_lines)
        period_text = month_start.strftime("%B %Y")
        description = build_playlist_description(period_text, lineup_str)
        playlist_url = (
            playlist.youtube_playlist_url or f"https://www.youtube.com/playlist?list={playlist.youtube_playlist_id}"
        )
        caption = build_caption(description, playlist_url, INSTAGRAM_HASHTAGS)

        self.stdout.write(f"Playlist: {playlist.id} — {month_label}")
        self.stdout.write(f"Entries: {len(entries)}")
        if dry_run:
            self.stdout.write("\n--- CAPTION ---")
            self.stdout.write(caption)
            self.stdout.write(f"\nCaption length: {len(caption)} chars")

        # --- Generate images ---
        cover_entries = [(e.position, e.song.performer.name) for e in entries]
        title = f"HAKKO-AKKEI {month_label.upper()} TOKYO Playlist"
        cover_bytes = generate_playlist_cover(title, month_label, cover_entries)
        self.stdout.write(f"Generated cover image ({len(cover_bytes):,} bytes)")

        images: list[tuple[bytes, str]] = [(cover_bytes, "cover.jpg")]

        for entry in entries:
            performer = entry.song.performer
            schedules = list(
                PerformanceSchedule.objects.filter(
                    performers=performer,
                    performance_date__gte=month_start,
                    performance_date__lt=month_end,
                )
                .select_related("live_house")
                .order_by("performance_date")
            )
            card_bytes = generate_performer_card(performer, entry.position, schedules)
            filename = f"performer_{entry.position:02d}_{performer.name[:20].replace(' ', '_')}.jpg"
            images.append((card_bytes, filename))
            self.stdout.write(f"Generated card for {performer.name} ({len(card_bytes):,} bytes)")

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nDry run complete — {len(images)} images generated, not posted"))
            return

        # --- Validate settings ---
        if not settings.INSTAGRAM_USER_ID:
            self.stderr.write(self.style.ERROR("INSTAGRAM_USER_ID not set in .env"))
            return

        cert_file = settings.OAUTH_LOCALHOST_CERT
        key_file = settings.OAUTH_LOCALHOST_KEY
        token_cache = cert_file.parent / "instagram_token.pickle"

        token = get_instagram_token(cert_file, key_file, token_cache)
        self.stdout.write("Instagram token loaded")

        post_id = post_carousel(settings.INSTAGRAM_USER_ID, token.access_token, images, caption)
        self.stdout.write(self.style.SUCCESS(f"Posted to Instagram: post_id={post_id}"))
