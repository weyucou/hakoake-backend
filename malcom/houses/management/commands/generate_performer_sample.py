"""Download performer song audio samples from YouTube for use in Shorts videos."""

import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from houses.functions import PERFORMER_SAMPLES_DIR, download_performer_song_audio
from houses.models import MonthlyPlaylist, WeeklyPlaylist
from performers.models import Performer

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Download performer song audio samples from their registered YouTube song items. "
        "Cached files are saved to data/performer_samples/<song_id>.mp3 and reused by "
        "generate_playlist_video --format shorts."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--monthly-playlist-id",
            type=int,
            help="Download samples for all performers in a monthly playlist",
        )
        group.add_argument(
            "--weekly-playlist-id",
            type=int,
            help="Download samples for all performers in a weekly playlist",
        )
        group.add_argument(
            "--performer-id",
            type=int,
            help="Download sample for a single performer",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download even if a cached sample already exists",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        force: bool = options["force"]
        samples_dir = Path(settings.BASE_DIR) / "data" / PERFORMER_SAMPLES_DIR
        samples_dir.mkdir(parents=True, exist_ok=True)

        songs = self._resolve_songs(options)
        if not songs:
            self.stderr.write(self.style.ERROR("No songs found for the given arguments."))
            return

        self.stdout.write(f"Processing {len(songs)} song(s). Cache dir: {samples_dir}\n")
        ok = 0
        skipped = 0
        failed = 0

        for song in songs:
            if not song.youtube_url:
                self.stdout.write(f"  SKIP  {song.performer.name} — no YouTube URL registered")
                skipped += 1
                continue

            cached = samples_dir / f"{song.id}.mp3"
            if cached.exists() and not force:
                self.stdout.write(f"  CACHE {song.performer.name}: {cached.name}")
                ok += 1
                continue

            self.stdout.write(f"  DL    {song.performer.name}: {song.youtube_url}")
            result = download_performer_song_audio(song, force=force)
            if result:
                self.stdout.write(self.style.SUCCESS(f"         → {result.name}"))
                ok += 1
            else:
                self.stderr.write(self.style.ERROR("         ✗ download failed"))
                failed += 1

        self.stdout.write(f"\nDone — ok: {ok}  skipped: {skipped}  failed: {failed}")

    def _resolve_songs(self, options: dict) -> list:  # noqa: ANN001, PLR0911
        monthly_id: int | None = options.get("monthly_playlist_id")
        weekly_id: int | None = options.get("weekly_playlist_id")
        performer_id: int | None = options.get("performer_id")

        if monthly_id is not None:
            try:
                playlist = MonthlyPlaylist.objects.get(id=monthly_id)
            except MonthlyPlaylist.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"MonthlyPlaylist id={monthly_id} not found"))
                return []
            return [
                entry.song
                for entry in playlist.monthlyplaylistentry_set.select_related("song__performer").order_by("position")
            ]

        if weekly_id is not None:
            try:
                playlist = WeeklyPlaylist.objects.get(id=weekly_id)
            except WeeklyPlaylist.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"WeeklyPlaylist id={weekly_id} not found"))
                return []
            return [
                entry.song
                for entry in playlist.weeklyplaylistentry_set.select_related("song__performer").order_by("position")
            ]

        if performer_id is not None:
            try:
                performer = Performer.objects.get(id=performer_id)
            except Performer.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Performer id={performer_id} not found"))
                return []
            songs = list(performer.songs.filter(youtube_url__gt="").order_by("id"))
            if not songs:
                self.stderr.write(self.style.WARNING(f"Performer {performer.name} has no songs with a YouTube URL"))
            return songs

        return []
