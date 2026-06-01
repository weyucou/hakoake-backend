"""Post a weekly playlist announcement to Threads.

Posts the playlist description and YouTube link as a text-based Threads post.
The post text mirrors the YouTube playlist description (build_playlist_description)
with the YouTube URL appended. Text is truncated at a performer-line boundary if
the total exceeds the 500-character Threads limit.

Usage:
    uv run python manage.py post_weekly_playlist_threads <playlist_id>
    uv run python manage.py post_weekly_playlist_threads <playlist_id> --dry-run
"""

from __future__ import annotations

import logging
from datetime import timedelta

from commons.threads_utils import _build_weekly_thread_text, create_thread_post, get_threads_token
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from houses.formatting import build_lineup_lines
from houses.models import WeeklyPlaylist, WeeklyPlaylistEntry

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Post a weekly playlist announcement to Threads"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "playlist_id",
            type=int,
            help="WeeklyPlaylist pk",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log post text without publishing to Threads",
        )

    def handle(self, *args: object, **options: object) -> None:
        playlist_id: int = options["playlist_id"]  # type: ignore[assignment]
        dry_run: bool = options["dry_run"]  # type: ignore[assignment]

        try:
            playlist = WeeklyPlaylist.objects.get(id=playlist_id)
        except WeeklyPlaylist.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"WeeklyPlaylist id={playlist_id} not found"))
            return

        entries = list(
            WeeklyPlaylistEntry.objects.filter(playlist=playlist).order_by("position").select_related("song__performer")
        )
        if not entries:
            self.stderr.write(self.style.ERROR("Playlist has no entries"))
            return

        week_start = playlist.date
        week_end = week_start + timedelta(days=7)
        performer_song_pairs = [(e.song.performer, e.song) for e in entries]
        lineup_lines = build_lineup_lines(performer_song_pairs, week_start, week_end)

        post_text = _build_weekly_thread_text(playlist, lineup_lines)
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
