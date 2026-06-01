"""Post a monthly playlist announcement to Threads.

Posts the playlist description and YouTube link as a text-based Threads post.
Text is truncated at a performer-line boundary if the total exceeds the
500-character Threads limit.

Usage:
    uv run python manage.py post_monthly_playlist_threads 2026-05
    uv run python manage.py post_monthly_playlist_threads 2026-05 --dry-run
"""

from __future__ import annotations

import logging

from commons.functions import get_month_end, parse_month
from commons.threads_utils import _build_monthly_thread_text, create_thread_post, get_threads_token
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from houses.formatting import build_lineup_lines
from houses.models import MonthlyPlaylist, MonthlyPlaylistEntry

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Post a monthly playlist announcement to Threads"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "target_month",
            type=str,
            help="Target month in YYYY-MM format",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log post text without publishing to Threads",
        )

    def handle(self, *args: object, **options: object) -> None:
        target_month_str: str = options["target_month"]  # type: ignore[assignment]
        dry_run: bool = options["dry_run"]  # type: ignore[assignment]

        try:
            target_date = parse_month(target_month_str)
        except ValueError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        try:
            playlist = MonthlyPlaylist.objects.get(date=target_date)
        except MonthlyPlaylist.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"MonthlyPlaylist for {target_month_str} not found"))
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
        performer_song_pairs = [(e.song.performer, e.song) for e in entries]
        lineup_lines = build_lineup_lines(performer_song_pairs, month_start, month_end)

        post_text = _build_monthly_thread_text(playlist, lineup_lines)
        self.stdout.write(f"Post text ({len(post_text)} chars):\n{post_text}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run — not published"))
            return

        cert_file = settings.OAUTH_LOCALHOST_CERT
        key_file = settings.OAUTH_LOCALHOST_KEY
        token_cache = cert_file.parent / "threads_token.json"
        token = get_threads_token(cert_file, key_file, token_cache)

        thread_id = create_thread_post(token.user_id, token.access_token, post_text)
        self.stdout.write(self.style.SUCCESS(f"Published to Threads: thread_id={thread_id}"))
