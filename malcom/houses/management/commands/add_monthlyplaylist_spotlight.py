from argparse import ArgumentParser

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from houses.models import MonthlyPlaylist, MonthlyPlaylistEntry
from performers.models import Performer, PerformerSong


class Command(BaseCommand):
    help = "Add a performer's most popular song as a spotlight entry (performer must be performing in target month)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--playlist-id",
            type=int,
            required=True,
            help="ID of the MonthlyPlaylist to add the spotlight song to",
        )
        parser.add_argument(
            "--performer-id",
            type=int,
            required=True,
            help="ID of the Performer whose song to add as spotlight",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        """
        Add a performer's most popular song as a spotlight entry to a monthly playlist.

        The command finds the performer's most popular song (by youtube_view_count)
        that is not yet in any monthly playlist, and adds it to the specified playlist
        with is_spotlight=True.

        Requirements:
        - Performer must have at least one performance scheduled in the target playlist month
        - Performer cannot already have a song in the target playlist

        Songs are filtered by:
        - Must have YouTube view count data
        - Duration must be >= MIN_SONG_SELECTION_DURATION_SECONDS (default: 25 seconds)
        - Duration must be <= MAX_SONG_SELECTION_DURATION_MINUTES (default: 10 minutes)
        - Must not already be in any playlist

        IMPORTANT: Spotlight entries do NOT affect the performer's playlist_weight.
        This ensures that manual spotlight additions don't interfere with the automatic
        rotation system used by create_monthly_playlist.
        """
        playlist_id = options["playlist_id"]
        performer_id = options["performer_id"]

        # Validate playlist exists
        try:
            playlist = MonthlyPlaylist.objects.get(id=playlist_id)
        except MonthlyPlaylist.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"MonthlyPlaylist with ID {playlist_id} does not exist."))
            return

        # Validate performer exists
        try:
            performer = Performer.objects.get(id=performer_id)
        except Performer.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Performer with ID {performer_id} does not exist."))
            return

        # Validate performer is performing in the target month
        month_start = playlist.date.replace(day=1)
        if playlist.date.month == 12:  # noqa: PLR2004
            month_end = playlist.date.replace(year=playlist.date.year + 1, month=1, day=1)
        else:
            month_end = playlist.date.replace(month=playlist.date.month + 1, day=1)

        performances_in_month = performer.performance_schedules.filter(
            performance_date__gte=month_start,
            performance_date__lt=month_end,
        )

        if not performances_in_month.exists():
            self.stdout.write(
                self.style.ERROR(
                    f"Performer '{performer.name}' has no scheduled performances in "
                    f"{playlist.date.strftime('%B %Y')}.\n"
                    f"Spotlight performers must be performing in the target playlist month."
                )
            )
            return

        # Check if performer already has a song in this playlist
        existing_entry = MonthlyPlaylistEntry.objects.filter(playlist=playlist, song__performer=performer).first()

        if existing_entry:
            self.stdout.write(
                self.style.ERROR(
                    f"Performer '{performer.name}' already has a song in this playlist.\n"
                    f"  Existing song: {existing_entry.song.title}\n"
                    f"  Position: {existing_entry.position}\n"
                    f"  Spotlight: {existing_entry.is_spotlight}"
                )
            )
            return

        # Get songs already in any playlist
        songs_in_playlists = MonthlyPlaylistEntry.objects.values_list("song_id", flat=True)

        # Get performer's songs not yet in any playlist, ordered by view count (most popular first)
        # Exclude songs shorter than MIN_SONG_SELECTION_DURATION_SECONDS
        # Exclude songs longer than MAX_SONG_SELECTION_DURATION_MINUTES
        min_duration_seconds = settings.MIN_SONG_SELECTION_DURATION_SECONDS
        max_duration_seconds = settings.MAX_SONG_SELECTION_DURATION_MINUTES * 60
        available_songs = (
            PerformerSong.objects.filter(performer=performer)
            .exclude(id__in=songs_in_playlists)
            .filter(
                youtube_view_count__isnull=False,  # Only songs with view count data
                youtube_duration_seconds__gte=min_duration_seconds,  # Exclude songs that are too short
                youtube_duration_seconds__lte=max_duration_seconds,  # Exclude songs that are too long
            )
            .order_by("-youtube_view_count")
        )

        if not available_songs.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"No available songs found for performer '{performer.name}'. "
                    f"All songs may already be in playlists or have no YouTube view count data."
                )
            )
            return

        # Get the most popular song
        most_popular_song = available_songs.first()

        # Create the spotlight entry
        # NOTE: Spotlight entries do NOT affect playlist_weight. The playlist_weight system
        # is used by create_monthly_playlist to ensure fair rotation of performers in
        # automatic playlist generation. Spotlight entries are manual/special additions
        # and should not interfere with the automatic rotation system.
        with transaction.atomic():
            # Get the next position in the playlist
            last_entry = MonthlyPlaylistEntry.objects.filter(playlist=playlist).order_by("-position").first()
            next_position = (last_entry.position + 1) if last_entry else 1

            # Create the entry
            entry = MonthlyPlaylistEntry.objects.create(
                playlist=playlist,
                song=most_popular_song,
                position=next_position,
                is_spotlight=True,
            )

        # Output success message
        self.stdout.write(self.style.SUCCESS(f"\n{'=' * 80}"))
        self.stdout.write(self.style.SUCCESS("SPOTLIGHT SONG ADDED"))
        self.stdout.write(self.style.SUCCESS(f"{'=' * 80}\n"))
        self.stdout.write(f"Playlist:        {playlist.date} (ID: {playlist.id})")
        self.stdout.write(f"Performer:       {performer.name} (ID: {performer.id})")
        self.stdout.write(f"Song:            {most_popular_song.title}")
        self.stdout.write(f"YouTube URL:     {most_popular_song.youtube_url or 'N/A'}")
        self.stdout.write(f"View Count:      {most_popular_song.youtube_view_count:,}")
        self.stdout.write(f"Position:        {entry.position}")
        self.stdout.write(f"Is Spotlight:    {entry.is_spotlight}")
        self.stdout.write(self.style.SUCCESS(f"\n{'=' * 80}\n"))
