"""Shared formatting utilities for playlist management commands."""

from .models import PerformanceSchedule


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
