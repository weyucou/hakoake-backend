"""Shared formatting utilities for playlist management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .definitions import PLAYLIST_TAGS
from .models import PerformanceSchedule

if TYPE_CHECKING:
    import datetime

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


def build_lineup_lines(
    selected_songs: list[tuple[Performer, PerformerSong]],
    date_start: datetime.date,
    date_end: datetime.date,
) -> list[str]:
    """Build formatted lineup lines from selected performers and their schedules."""
    lines = []
    for idx, (performer, _song) in enumerate(selected_songs, start=1):
        schedules = performer.performance_schedules.filter(
            performance_date__gte=date_start,
            performance_date__lt=date_end,
        ).select_related("live_house")
        seen = set()
        for sched in schedules:
            key = (sched.live_house_id, sched.performance_date)
            if key in seen:
                continue
            seen.add(key)
            venue_name = sched.live_house.name
            date_str = sched.performance_date.strftime("%Y-%m-%d (%a)")
            lines.append(f"{idx}. {date_str} {performer.name} @ {venue_name}")
    return lines


def build_playlist_description(period_text: str, lineup_str: str) -> str:
    """Build YouTube playlist description with lineup and tags."""
    tags_str = "\n".join(f"#{t}" for t in PLAYLIST_TAGS)
    return f"""Discover bands performing in TOKYO Live Houses for {period_text}.

{lineup_str}

{tags_str}"""
