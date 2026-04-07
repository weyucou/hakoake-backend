"""
Creates a WeeklyPlaylist for a given target_week.

This command:
1. Selects the top N Performers performing in the target week, ordered by playlist_weight (highest first)
    - exclude performers without a verified YouTube PerformerSocialLink (verified_datetime must be set)
    - exclude performers without a PerformerSong with valid `youtube_video_id` and `youtube_url`
    - exclude songs shorter than MIN_SONG_SELECTION_DURATION_SECONDS (default: 25 seconds)
    - exclude songs longer than MAX_SONG_SELECTION_DURATION_MINUTES (default: 10 minutes)
    - NO song exclusion based on prior playlist inclusion (unlike monthly - uses pure rotation)
2. For each performer, selects their most popular song (by youtube_view_count)
3. Creates a YouTube playlist with these songs
4. Creates WeeklyPlaylist and WeeklyPlaylistEntry records
5. Updates playlist_weight:
   - Selected performers (top N): reset to 0
   - Non-selected performers: increment by 1
"""

import logging
from datetime import date, timedelta
from pathlib import Path

from commons.functions import parse_week
from commons.youtube_utils import add_video_to_playlist, create_youtube_playlist, get_video_durations
from django.conf import settings
from django.core.management import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from houses.formatting import build_lineup_lines, build_playlist_description
from houses.models import WeeklyPlaylist, WeeklyPlaylistEntry
from performers.models import Performer, PerformerSocialLink, PerformerSong

logger = logging.getLogger(__name__)

# Constants
DEFAULT_TOP_PERFORMERS_COUNT = 5

# PerformerSong rows last touched before this date were ingested by an earlier
# extraction path that occasionally stored stale ``youtube_duration_seconds``
# values (see hakoake-backend playlist incident on 2026-04-06 where a 41-minute
# live recording was stored as a short clip). For any candidate song whose
# ``updated_datetime`` is before this cutoff we re-verify the actual duration
# against the YouTube API before applying the playlist duration filter, then
# bump ``updated_datetime`` so subsequent runs skip the row.
DURATION_REVERIFICATION_CUTOFF_DATE = date(2026, 3, 30)


class Command(BaseCommand):
    help = "Create a weekly playlist for the top N performers by playlist_weight"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "target_week",
            type=str,
            nargs="?",
            default=None,
            help="Target week start date in YYYY-MM-DD format (must be a Monday). Defaults to next week.",
        )
        parser.add_argument(
            "--top-n",
            type=int,
            default=DEFAULT_TOP_PERFORMERS_COUNT,
            help=f"Number of top performers to include (default: {DEFAULT_TOP_PERFORMERS_COUNT})",
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

    def _reverify_legacy_song_durations(
        self,
        eligible_performers: list[Performer],
        min_duration_seconds: int,
        max_duration_seconds: int,
        secrets_file: Path,
    ) -> None:
        """Re-verify YouTube durations for legacy candidate songs.

        The candidate filter relies on ``auto_now`` having stamped
        ``updated_datetime`` at last save: anything before
        ``DURATION_REVERIFICATION_CUTOFF_DATE`` is treated as legacy. Every
        processed row's ``updated_datetime`` is bumped (even when the duration
        matched) so subsequent runs converge — once the legacy backlog drains,
        this method becomes a no-op. Videos missing from the API response are
        set to ``youtube_duration_seconds=0`` to exclude them downstream.
        """
        candidate_rows = list(
            PerformerSong.objects.filter(
                performer__in=eligible_performers,
                updated_datetime__date__lt=DURATION_REVERIFICATION_CUTOFF_DATE,
                youtube_video_id__isnull=False,
                youtube_duration_seconds__gte=min_duration_seconds,
                youtube_duration_seconds__lte=max_duration_seconds,
            )
            .exclude(youtube_video_id="")
            .values_list("id", "youtube_video_id", "youtube_duration_seconds")
        )

        if not candidate_rows:
            return

        self.stdout.write(
            f"Re-verifying YouTube durations for {len(candidate_rows)} legacy candidate song(s) "
            f"(updated_datetime before {DURATION_REVERIFICATION_CUTOFF_DATE.isoformat()})..."
        )

        video_ids = [video_id for _, video_id, _ in candidate_rows]
        actual_durations = get_video_durations(video_ids, secrets_file)

        updates = 0
        unavailable_ids: list[int] = []
        unchanged_ids: list[int] = []
        now = timezone.now()
        for song_id, video_id, db_duration in candidate_rows:
            actual = actual_durations.get(video_id)
            if actual is None:
                unavailable_ids.append(song_id)
                self.stdout.write(
                    self.style.WARNING(
                        f"  song id={song_id} video={video_id} unavailable on YouTube; duration set to 0"
                    )
                )
                continue
            if actual != db_duration:
                PerformerSong.objects.filter(pk=song_id).update(
                    youtube_duration_seconds=actual,
                    updated_datetime=now,
                )
                updates += 1
                self.stdout.write(f"  song id={song_id} video={video_id} duration {db_duration}s -> {actual}s")
            else:
                unchanged_ids.append(song_id)

        if unavailable_ids:
            PerformerSong.objects.filter(pk__in=unavailable_ids).update(
                youtube_duration_seconds=0,
                updated_datetime=now,
            )
        if unchanged_ids:
            PerformerSong.objects.filter(pk__in=unchanged_ids).update(updated_datetime=now)

        self.stdout.write(
            f"Re-verification complete: {updates} duration update(s), "
            f"{len(unavailable_ids)} unavailable video(s), {len(unchanged_ids)} verified-unchanged"
        )

    def handle(self, *args, **options):  # noqa: ANN002, ANN003, C901, PLR0911, PLR0912, PLR0915
        target_week_str = options["target_week"]
        top_n = options["top_n"]
        secrets_file = Path(options["secrets_file"])
        dry_run = options["dry_run"]

        # Validate top_n
        if top_n < 1:
            self.stderr.write(self.style.ERROR("--top-n must be at least 1"))
            return

        # Parse target week (defaults to next week)
        try:
            target_date = parse_week(target_week_str, default_to_next_week=True)
        except ValueError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(f"Creating weekly playlist for week starting {target_date.strftime('%Y-%m-%d')}")

        # Check if playlist already exists for this week
        if WeeklyPlaylist.objects.filter(date=target_date).exists():
            self.stderr.write(
                self.style.ERROR(f"WeeklyPlaylist already exists for week starting {target_date.strftime('%Y-%m-%d')}")
            )
            return

        # Check if secrets file exists (only needed for non-dry-run)
        if not dry_run and not secrets_file.exists():
            self.stderr.write(self.style.ERROR(f"Secrets file not found: {secrets_file}"))
            self.stdout.write("Please provide a valid Google OAuth secrets file using --secrets-file")
            return

        # Calculate week boundaries
        week_start = target_date
        week_end = week_start + timedelta(days=7)

        # Get IDs of performers who have a verified YouTube social link
        performers_with_verified_youtube = (
            PerformerSocialLink.objects.filter(
                platform="youtube",
                verified_datetime__isnull=False,
            )
            .values_list("performer_id", flat=True)
            .distinct()
        )

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
        # 1. Have a verified YouTube social link
        # 2. Have at least one YouTube song
        # 3. Are scheduled to perform in the target week
        eligible_performers = list(
            Performer.objects.filter(
                id__in=performers_with_verified_youtube,
            )
            .filter(
                id__in=performers_with_songs,
                performance_schedules__performance_date__gte=week_start,
                performance_schedules__performance_date__lt=week_end,
            )
            .distinct()
            .order_by("-playlist_weight", "name")
        )

        if not eligible_performers:
            week_str = target_date.strftime("%Y-%m-%d")
            self.stderr.write(
                self.style.ERROR(
                    f"No performers with verified YouTube links and songs scheduled for week starting {week_str} found"
                )
            )
            return

        min_duration_seconds = settings.MIN_SONG_SELECTION_DURATION_SECONDS
        max_duration_seconds = settings.MAX_SONG_SELECTION_DURATION_MINUTES * 60

        # Re-verify legacy song durations before filtering. Out-of-range songs
        # cannot be selected anyway, so we skip them to save API quota.
        if not dry_run:
            self._reverify_legacy_song_durations(
                eligible_performers,
                min_duration_seconds,
                max_duration_seconds,
                secrets_file,
            )

        # Select performers with unique songs (deduplicate by video_id)
        # NOTE: Weekly playlists do NOT exclude songs from previous playlists
        # They rely purely on playlist_weight rotation for fair selection
        selected_songs = []
        used_video_ids = set()

        for performer in eligible_performers:
            if len(selected_songs) >= top_n:
                break

            # Get most popular song by youtube_view_count
            # Exclude songs shorter than MIN_SONG_SELECTION_DURATION_SECONDS
            # Exclude songs longer than MAX_SONG_SELECTION_DURATION_MINUTES
            most_popular_song = (
                PerformerSong.objects.filter(
                    performer=performer,
                    youtube_video_id__isnull=False,
                    youtube_duration_seconds__gte=min_duration_seconds,
                    youtube_duration_seconds__lte=max_duration_seconds,
                )
                .exclude(youtube_video_id="")
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

        if len(selected_songs) < top_n:
            self.stderr.write(
                self.style.ERROR(
                    f"Cannot create playlist: only {len(selected_songs)} performers with verified YouTube links "
                    f"found (need {top_n}). Verify more performer YouTube links to continue."
                )
            )
            return

        lineup_lines = build_lineup_lines(selected_songs, week_start, week_end)

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
        week_date_str = target_date.strftime("%Y-%m-%d")
        playlist_title = f"HAKKO-AKKEI WEEK {week_date_str} TOKYO Playlist"
        playlist_description = build_playlist_description(f"week of {week_date_str}", "\n".join(lineup_lines))

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
            # Create WeeklyPlaylist
            youtube_playlist_url = f"https://www.youtube.com/playlist?list={youtube_playlist_id}"
            channel_url = getattr(settings, "YOUTUBE_CHANNEL_URL", "")

            weekly_playlist = WeeklyPlaylist.objects.create(
                date=target_date,
                youtube_playlist_id=youtube_playlist_id,
                youtube_playlist_url=youtube_playlist_url,
                youtube_channel_url=channel_url,
            )
            self.stdout.write(f"\nCreated WeeklyPlaylist for week starting {target_date.strftime('%Y-%m-%d')}")

            # Create WeeklyPlaylistEntry records
            for position, (performer, song) in enumerate(added_songs, start=1):
                WeeklyPlaylistEntry.objects.create(
                    playlist=weekly_playlist,
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
            self.style.SUCCESS(f"\n Successfully created weekly playlist: {youtube_playlist_id}"),
        )
        self.stdout.write(f"  YouTube URL: https://www.youtube.com/playlist?list={youtube_playlist_id}")
