from argparse import ArgumentParser
from datetime import date, datetime

from commons.functions import get_month_end
from django.core.management.base import BaseCommand
from houses.formatting import format_duration
from houses.models import MonthlyPlaylist, MonthlyPlaylistEntry, PerformanceSchedule


class Command(BaseCommand):
    help = (
        "List performers from monthly playlist with their performance in the playlist month (matching video generation)"
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--month",
            type=str,
            help="Target month in MM or YYYY-MM format. Defaults to current month.",
        )
        parser.add_argument(
            "--upcoming-only",
            action="store_true",
            help="Only show upcoming performances (performance date >= today)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, C901, PLR0912, PLR0915
        """
        List performers from a monthly playlist with their performance venue and cost information.

        Shows only the first performance in the playlist month for each performer.
        This matches the performance shown in the video generation.
        Outputs: position, performer_id, performer_name, venue_name, performance_date,
        presale_price, door_price, song_title, duration, youtube_url
        """
        month_str = options.get("month")
        upcoming_only = options.get("upcoming_only", False)

        # Determine target month
        if month_str:
            try:
                # Try MM format first (month in current year)
                if len(month_str) == 2:  # noqa: PLR2004
                    today = date.today()  # noqa: DTZ011
                    month = int(month_str)
                    if month < 1 or month > 12:  # noqa: PLR2004
                        raise ValueError("Month must be between 01 and 12")  # noqa: TRY301
                    target_date = date(today.year, month, 1)
                # Try YYYY-MM format
                elif len(month_str) == 7:  # noqa: PLR2004
                    target_date = datetime.strptime(month_str, "%Y-%m").date()  # noqa: DTZ007
                else:
                    self.stdout.write(self.style.ERROR(f"Invalid month format: {month_str}. Use MM or YYYY-MM."))
                    return
            except ValueError as e:
                self.stdout.write(self.style.ERROR(f"Invalid month: {month_str}. {e}"))
                return
        else:
            # Default to current month
            today = date.today()  # noqa: DTZ011
            target_date = date(today.year, today.month, 1)

        # Find the playlist for this month
        try:
            playlist = MonthlyPlaylist.objects.get(date=target_date)
        except MonthlyPlaylist.DoesNotExist:
            month_display = target_date.strftime("%B %Y")
            self.stdout.write(self.style.WARNING(f"No playlist found for {month_display}."))
            return

        # Print title header
        self.stdout.write("")  # Empty line
        month_display = playlist.date.strftime("%B %Y")
        self.stdout.write(f"Monthly Playlist - {month_display} (Playlist ID: {playlist.id})")
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
            MonthlyPlaylistEntry.objects.filter(playlist=playlist)
            .select_related("song__performer")
            .order_by("position")
        )

        if not entries.exists():
            self.stdout.write(self.style.WARNING("No entries in this playlist."))
            return

        # Track unique performers for this playlist
        performers_in_playlist = set()

        for entry in entries:
            performer = entry.song.performer
            performers_in_playlist.add(performer.id)

            # Calculate month boundaries (same logic as video generation)
            month_start = playlist.date
            month_end = get_month_end(month_start)

            # Get performance schedules for this performer in the playlist month
            schedules = PerformanceSchedule.objects.filter(
                performers=performer,
                performance_date__gte=month_start,
                performance_date__lt=month_end,
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
                duration = format_duration(entry.song.youtube_duration_seconds)
                youtube_url = entry.song.youtube_url or "-"

                self.stdout.write(
                    f"{entry.position:<5} {performer.id:<15} {performer.name[:28]:<30} "
                    f"{first_schedule.live_house.name[:28]:<30} {str(first_schedule.performance_date):<18} "
                    f"{presale:<10} {door:<10} {song_title:<40} {duration:<10} {youtube_url:<60}"
                )
            else:
                song_title = entry.song.title[:38] if entry.song.title else "-"
                duration = format_duration(entry.song.youtube_duration_seconds)
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
