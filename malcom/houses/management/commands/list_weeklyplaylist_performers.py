"""
List performers from a weekly playlist with their performance in the playlist week.

Shows only the first performance in the playlist week for each performer.
This matches the performance shown in the video generation.
"""

from argparse import ArgumentParser
from datetime import date, timedelta

from commons.functions import parse_week
from django.core.management.base import BaseCommand
from houses.models import PerformanceSchedule, WeeklyPlaylist, WeeklyPlaylistEntry


class Command(BaseCommand):
    help = (
        "List performers from weekly playlist with their performance in the playlist week (matching video generation)"
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--week",
            type=str,
            help="Target week in YYYY-MM-DD format (must be a Monday). Defaults to current week.",
        )
        parser.add_argument(
            "--upcoming-only",
            action="store_true",
            help="Only show upcoming performances (performance date >= today)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, C901, PLR0912, PLR0915
        """
        List performers from a weekly playlist with their performance venue and cost information.

        Shows only the first performance in the playlist week for each performer.
        This matches the performance shown in the video generation.
        Outputs: position, performer_id, performer_name, venue_name, performance_date,
        presale_price, door_price, song_title, duration, youtube_url
        """
        week_str = options.get("week")
        upcoming_only = options.get("upcoming_only", False)

        # Parse target week (defaults to current week)
        try:
            target_date = parse_week(week_str, default_to_next_week=False)
        except ValueError as e:
            self.stdout.write(self.style.ERROR(str(e)))
            return

        # Find the playlist for this week
        try:
            playlist = WeeklyPlaylist.objects.get(date=target_date)
        except WeeklyPlaylist.DoesNotExist:
            week_display = target_date.strftime("%Y-%m-%d")
            self.stdout.write(self.style.WARNING(f"No playlist found for week starting {week_display}."))
            return

        # Print title header
        self.stdout.write("")  # Empty line
        week_display = playlist.date.strftime("%Y-%m-%d")
        self.stdout.write(f"Weekly Playlist - Week of {week_display} (Playlist ID: {playlist.id})")
        self.stdout.write("")  # Empty line

        # Print column header
        self.stdout.write(
            f"{'Pos':<5} {'Performer ID':<15} {'Performer Name':<30} "
            f"{'Venue':<30} {'Performance Date':<18} {'Presale':<10} {'Door':<10} "
            f"{'Song Title':<40} {'Duration':<10} {'YouTube URL':<60}"
        )
        self.stdout.write("-" * 240)

        today = date.today()  # noqa: DTZ011

        # Get all entries for this playlist
        entries = (
            WeeklyPlaylistEntry.objects.filter(playlist=playlist).select_related("song__performer").order_by("position")
        )

        if not entries.exists():
            self.stdout.write(self.style.WARNING("No entries in this playlist."))
            return

        # Track unique performers for this playlist
        performers_in_playlist = set()

        # Calculate week boundaries
        week_start = playlist.date
        week_end = week_start + timedelta(days=7)

        for entry in entries:
            performer = entry.song.performer
            performers_in_playlist.add(performer.id)

            # Get performance schedules for this performer in the playlist week
            schedules = PerformanceSchedule.objects.filter(
                performers=performer,
                performance_date__gte=week_start,
                performance_date__lt=week_end,
            ).select_related("live_house")

            # Apply additional date filter if upcoming_only is set
            if upcoming_only:
                schedules = schedules.filter(performance_date__gte=today)

            schedules = schedules.order_by("performance_date", "start_time")

            # Show only the first/next performance for each performer
            first_schedule = schedules.first()

            if first_schedule:
                presale = f"¥{first_schedule.presale_price:,.0f}" if first_schedule.presale_price else "-"
                door = f"¥{first_schedule.door_price:,.0f}" if first_schedule.door_price else "-"
                song_title = entry.song.title[:38] if entry.song.title else "-"

                # Format duration as MM:SS
                if entry.song.youtube_duration_seconds:
                    minutes = entry.song.youtube_duration_seconds // 60
                    seconds = entry.song.youtube_duration_seconds % 60
                    duration = f"{minutes}:{seconds:02d}"
                else:
                    duration = "-"

                youtube_url = entry.song.youtube_url or "-"

                self.stdout.write(
                    f"{entry.position:<5} {performer.id:<15} {performer.name[:28]:<30} "
                    f"{first_schedule.live_house.name[:28]:<30} {str(first_schedule.performance_date):<18} "
                    f"{presale:<10} {door:<10} {song_title:<40} {duration:<10} {youtube_url:<60}"
                )
            else:
                # Show performer even if they have no scheduled performances
                song_title = entry.song.title[:38] if entry.song.title else "-"

                # Format duration as MM:SS
                if entry.song.youtube_duration_seconds:
                    minutes = entry.song.youtube_duration_seconds // 60
                    seconds = entry.song.youtube_duration_seconds % 60
                    duration = f"{minutes}:{seconds:02d}"
                else:
                    duration = "-"

                youtube_url = entry.song.youtube_url or "-"
                self.stdout.write(
                    f"{entry.position:<5} {performer.id:<15} {performer.name[:28]:<30} "
                    f"{'(No scheduled performances)':<30} {'-':<18} {'-':<10} {'-':<10} "
                    f"{song_title:<40} {duration:<10} {youtube_url:<60}"
                )

        total_performers = len(performers_in_playlist)

        # Print summary
        self.stdout.write("-" * 240)
        self.stdout.write(f"Total performers: {total_performers}")
        self.stdout.write("")  # Empty line
