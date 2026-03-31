"""
Creates a MonthlyPlaylist for a given target_month.

This command:
1. Selects the top 5 Performers performing in the target_date month, ordered by playlist_weight (highest first)
    - exclude performers without a PerformerSong with valid `youtube_video_id` and `youtube_url`
    - exclude songs shorter than MIN_SONG_SELECTION_DURATION_SECONDS (default: 25 seconds)
    - exclude songs longer than MAX_SONG_SELECTION_DURATION_MINUTES (default: 10 minutes)
    - exclude songs already in any playlist
2. For each performer, selects their most popular song (by youtube_view_count)
3. Creates a YouTube playlist with these songs
4. Creates MonthlyPlaylist and MonthlyPlaylistEntry records
5. Updates playlist_weight:
   - Selected performers (top 5): reset to 0
   - Non-selected performers: increment by 1
"""

import logging
from pathlib import Path

from commons.functions import get_month_end, parse_month
from commons.youtube_utils import add_video_to_playlist, create_youtube_playlist
from django.conf import settings
from django.core.management import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from houses.formatting import build_lineup_lines, build_playlist_description
from houses.models import MonthlyPlaylist, MonthlyPlaylistEntry
from performers.models import Performer, PerformerSong

logger = logging.getLogger(__name__)

TOP_PERFORMERS_COUNT = 5


class Command(BaseCommand):
    help = "Create a monthly playlist for the top 5 performers by playlist_weight"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "target_month",
            type=str,
            help="Target month in YYYY-MM or YYYY-MM-DD format",
        )
        parser.add_argument(
            "--secrets-file",
            type=str,
            default="../client_secret.json",
            help="Path to Google OAuth secrets file (default: ../client_secret.json)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Perform a dry run without creating playlist or updating weights",
        )

    def handle(self, *args, **options):  # noqa: ANN002, ANN003, C901, PLR0911, PLR0912, PLR0915
        target_month_str = options["target_month"]
        secrets_file = Path(options["secrets_file"])
        dry_run = options["dry_run"]

        try:
            target_date = parse_month(target_month_str)
        except ValueError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(f"Creating monthly playlist for {target_date.strftime('%Y-%m')}")

        # Check if playlist already exists for this month
        if MonthlyPlaylist.objects.filter(date=target_date).exists():
            self.stderr.write(self.style.ERROR(f"MonthlyPlaylist already exists for {target_date.strftime('%Y-%m')}"))
            return

        # Check if secrets file exists
        if not secrets_file.exists():
            self.stderr.write(self.style.ERROR(f"Secrets file not found: {secrets_file}"))
            self.stdout.write("Please provide a valid Google OAuth secrets file using --secrets-file")
            return

        # Calculate month boundaries for filtering performances
        month_start = target_date
        month_end = get_month_end(month_start)

        # Get IDs of performers who have at least one valid YouTube song
        performers_with_songs = (
            PerformerSong.objects.filter(
                youtube_video_id__isnull=False,
            )
            .exclude(youtube_video_id="")
            .values_list("performer_id", flat=True)
            .distinct()
        )

        # Get eligible performers ordered by playlist_weight who:
        # 1. Have at least one YouTube song
        # 2. Are scheduled to perform in the target month
        eligible_performers = list(
            Performer.objects.filter(
                id__in=performers_with_songs,
                performance_schedules__performance_date__gte=month_start,
                performance_schedules__performance_date__lt=month_end,
            )
            .distinct()
            .order_by("-playlist_weight", "name")
        )

        if not eligible_performers:
            self.stderr.write(
                self.style.ERROR(
                    f"No performers with YouTube songs scheduled for {target_date.strftime('%Y-%m')} found"
                )
            )
            return

        # Get songs already in any playlist
        songs_in_playlists = MonthlyPlaylistEntry.objects.values_list("song_id", flat=True)

        # Select performers with unique songs (deduplicate by video_id)
        selected_songs = []
        used_video_ids = set()

        for performer in eligible_performers:
            if len(selected_songs) >= TOP_PERFORMERS_COUNT:
                break

            # Get most popular song by youtube_view_count
            # Exclude songs shorter than MIN_SONG_SELECTION_DURATION_SECONDS
            # Exclude songs longer than MAX_SONG_SELECTION_DURATION_MINUTES
            # Exclude songs already in any playlist
            min_duration_seconds = settings.MIN_SONG_SELECTION_DURATION_SECONDS
            max_duration_seconds = settings.MAX_SONG_SELECTION_DURATION_MINUTES * 60
            most_popular_song = (
                PerformerSong.objects.filter(
                    performer=performer,
                    youtube_video_id__isnull=False,
                    youtube_duration_seconds__gte=min_duration_seconds,
                    youtube_duration_seconds__lte=max_duration_seconds,
                )
                .exclude(youtube_video_id="")
                .exclude(id__in=songs_in_playlists)
                .order_by("-youtube_view_count", "title")
                .first()
            )

            if most_popular_song and most_popular_song.youtube_video_id not in used_video_ids:
                selected_songs.append((performer, most_popular_song))
                used_video_ids.add(most_popular_song.youtube_video_id)
                self.stdout.write(
                    f"  {performer.name}: {most_popular_song.title} "
                    f"(views: {most_popular_song.youtube_view_count or 0}, weight: {performer.playlist_weight})",
                )
            elif most_popular_song:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping {performer.name}: duplicate video {most_popular_song.youtube_video_id}"
                    )
                )

        if not selected_songs:
            self.stderr.write(self.style.ERROR("No songs with YouTube videos found for eligible performers"))
            return

        if len(selected_songs) < TOP_PERFORMERS_COUNT:
            self.stdout.write(
                self.style.WARNING(
                    f"Only {len(selected_songs)} unique performers/songs found (expected {TOP_PERFORMERS_COUNT})"
                ),
            )

        lineup_lines = build_lineup_lines(selected_songs, month_start, month_end)

        self.stdout.write("\nPlaylist lineup:")
        for line in lineup_lines:
            self.stdout.write(f"  - {line}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("\n=== DRY RUN - No changes made ==="))
            self.stdout.write(f"Would create playlist with {len(selected_songs)} songs")
            selected_performer_ids = [p.id for p, _ in selected_songs]
            self.stdout.write(f"Would reset playlist_weight to 0 for {len(selected_performer_ids)} performers")
            non_selected_count = Performer.objects.exclude(id__in=selected_performer_ids).count()
            self.stdout.write(f"Would increment playlist_weight for {non_selected_count} non-selected performers")
            return

        # Create YouTube playlist
        month_name = target_date.strftime("%B").upper()
        year = target_date.strftime("%Y")
        playlist_title = f"HAKKO-AKKEI {month_name} {year} TOKYO Playlist Introduction"
        month_name = target_date.strftime("%B")
        playlist_description = build_playlist_description(f"{month_name} {year}", "\n".join(lineup_lines))

        try:
            youtube_playlist_id = create_youtube_playlist(playlist_title, playlist_description, secrets_file)
        except Exception as e:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"Failed to create YouTube playlist: {e}"))
            return

        # Add songs to YouTube playlist (deduplicate by video_id)
        added_songs = []
        added_video_ids = set()
        for performer, song in selected_songs:
            # Skip if this video has already been added
            if song.youtube_video_id in added_video_ids:
                self.stdout.write(self.style.WARNING(f"  Skipping {performer.name} - duplicate video: {song.title}"))
                continue

            success = add_video_to_playlist(youtube_playlist_id, song.youtube_video_id, secrets_file)
            if success:
                added_songs.append((performer, song))
                added_video_ids.add(song.youtube_video_id)

        if not added_songs:
            self.stderr.write(self.style.ERROR("Failed to add any songs to YouTube playlist"))
            return

        # Create database records and update playlist_weight
        with transaction.atomic():
            # Create MonthlyPlaylist
            youtube_playlist_url = f"https://www.youtube.com/playlist?list={youtube_playlist_id}"
            channel_url = getattr(settings, "YOUTUBE_CHANNEL_URL", "")

            monthly_playlist = MonthlyPlaylist.objects.create(
                date=target_date,
                youtube_playlist_id=youtube_playlist_id,
                youtube_playlist_url=youtube_playlist_url,
                youtube_channel_url=channel_url,
            )
            self.stdout.write(f"\nCreated MonthlyPlaylist for {target_date.strftime('%Y-%m')}")

            # Create MonthlyPlaylistEntry records
            for position, (performer, song) in enumerate(added_songs, start=1):
                MonthlyPlaylistEntry.objects.create(
                    playlist=monthly_playlist,
                    position=position,
                    song=song,
                )
                self.stdout.write(f"  [{position}] {performer.name} - {song.title}")

            # Update playlist_weight for selected performers (reset to 0)
            selected_performer_ids = [p.id for p, _ in added_songs]
            Performer.objects.filter(id__in=selected_performer_ids).update(
                playlist_weight=0,
                playlist_weight_update_datetime=timezone.now(),
            )
            self.stdout.write(f"\nReset playlist_weight to 0 for {len(selected_performer_ids)} selected performers")

            # Update playlist_weight for non-selected performers (increment by 1)
            non_selected_updated = Performer.objects.exclude(id__in=selected_performer_ids).update(
                playlist_weight=F("playlist_weight") + 1,
                playlist_weight_update_datetime=timezone.now(),
            )
            self.stdout.write(f"Incremented playlist_weight for {non_selected_updated} non-selected performers")

        self.stdout.write(
            self.style.SUCCESS(f"\n✓ Successfully created monthly playlist: {youtube_playlist_id}"),
        )
        self.stdout.write(f"  YouTube URL: https://www.youtube.com/playlist?list={youtube_playlist_id}")
