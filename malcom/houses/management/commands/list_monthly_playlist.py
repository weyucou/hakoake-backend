"""
List the MonthlyPlaylist for a given target month.

Shows performer, song, and performance live-houses/dates for each playlist entry.
"""

import datetime
from argparse import ArgumentParser

from commons.functions import get_month_end, parse_month
from django.core.management.base import BaseCommand
from django.db.models import QuerySet
from houses.models import MonthlyPlaylist, MonthlyPlaylistEntry, PerformanceSchedule
from performers.models import Performer, PerformerSong


def format_duration(seconds: int | None) -> str:
    """Format duration in seconds as MM:SS string."""
    if not seconds:
        return "-"
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


def format_schedule_time(schedule: PerformanceSchedule) -> str:
    """Format open/start time for a schedule."""
    time_str = ""
    if schedule.open_time:
        time_str = f" OPEN {schedule.open_time.strftime('%H:%M')}"
    if schedule.start_time:
        time_str += f" START {schedule.start_time.strftime('%H:%M')}"
    return time_str


def format_schedule_price(schedule: PerformanceSchedule) -> str:
    """Format presale/door price for a schedule."""
    price_str = ""
    if schedule.presale_price:
        price_str = f" ADV ¥{schedule.presale_price:,.0f}"
    if schedule.door_price:
        price_str += f" DOOR ¥{schedule.door_price:,.0f}"
    return price_str


def get_month_boundaries(playlist_date: datetime.date) -> tuple[datetime.date, datetime.date]:
    """Calculate month start and end dates from playlist date."""
    return playlist_date, get_month_end(playlist_date)


def get_performer_schedules(
    performer: Performer, month_start: datetime.date, month_end: datetime.date
) -> QuerySet[PerformanceSchedule]:
    """Get performance schedules for a performer within a month range."""
    return (
        PerformanceSchedule.objects.filter(
            performers=performer,
            performance_date__gte=month_start,
            performance_date__lt=month_end,
        )
        .select_related("live_house")
        .order_by("performance_date", "start_time")
    )


class Command(BaseCommand):
    help = "List the monthly playlist with performer, song, and performance dates/venues"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "target_month",
            nargs="?",
            type=str,
            default=None,
            help="Target month in YYYY-MM or YYYY-MM-DD format (defaults to next month)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        target_month_str = options.get("target_month")

        # Parse target month (defaults to next month)
        try:
            target_date = parse_month(target_month_str, default_to_next_month=True)
        except ValueError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return

        # Find the playlist for this month
        try:
            playlist = MonthlyPlaylist.objects.get(date=target_date)
        except MonthlyPlaylist.DoesNotExist:
            month_display = target_date.strftime("%B %Y")
            self.stdout.write(self.style.WARNING(f"No playlist found for {month_display}."))
            return

        month_start, month_end = get_month_boundaries(playlist.date)
        self._print_header(playlist)

        entries = (
            MonthlyPlaylistEntry.objects.filter(playlist=playlist)
            .select_related("song__performer")
            .order_by("position")
        )

        if not entries.exists():
            self.stdout.write(self.style.WARNING("No entries in this playlist."))
            return

        for entry in entries:
            self._print_entry(entry, month_start, month_end)

        self.stdout.write(f"Total entries: {entries.count()}")

    def _print_header(self, playlist: MonthlyPlaylist) -> None:
        """Print playlist header information."""
        month_display = playlist.date.strftime("%B %Y")
        self.stdout.write("")
        self.stdout.write(f"Monthly Playlist - {month_display} (ID: {playlist.id})")
        if playlist.youtube_playlist_url:
            self.stdout.write(f"YouTube: {playlist.youtube_playlist_url}")
        self.stdout.write("")

    def _print_entry(self, entry: MonthlyPlaylistEntry, month_start: datetime.date, month_end: datetime.date) -> None:
        """Print a single playlist entry with performer, song, and schedules."""
        performer = entry.song.performer
        song = entry.song

        self._print_performer_info(entry, performer, song)
        self._print_schedules(performer, month_start, month_end)
        self.stdout.write("")  # Empty line between entries

    def _print_performer_info(self, entry: MonthlyPlaylistEntry, performer: Performer, song: PerformerSong) -> None:
        """Print performer and song information."""
        duration = format_duration(song.youtube_duration_seconds)
        spotlight_marker = " [SPOTLIGHT]" if entry.is_spotlight else ""

        self.stdout.write(f"[{entry.position}] {performer.name}{spotlight_marker}")
        self.stdout.write(f"    Song: {song.title} ({duration})")
        if song.youtube_url:
            self.stdout.write(f"    URL: {song.youtube_url}")

    def _print_schedules(self, performer: Performer, month_start: datetime.date, month_end: datetime.date) -> None:
        """Print performance schedules for a performer."""
        schedules = get_performer_schedules(performer, month_start, month_end)

        if not schedules.exists():
            self.stdout.write("    Performances: (none scheduled)")
            return

        self.stdout.write("    Performances:")
        for schedule in schedules:
            day_of_week = schedule.performance_date.strftime("%a")
            perf_date = schedule.performance_date.strftime("%Y-%m-%d")
            venue = schedule.live_house.name
            time_str = format_schedule_time(schedule)
            price_str = format_schedule_price(schedule)

            self.stdout.write(f"      - {perf_date} ({day_of_week}) @ {venue}{time_str}{price_str}")
