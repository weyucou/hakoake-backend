"""Common utility functions shared across the project."""

import datetime
import logging

import requests

YYYY_MM_LENGTH = 7
YYYY_MM_DD_LENGTH = 10

CATBOX_API_URL = "https://catbox.moe/user/api.php"

logger = logging.getLogger(__name__)


class CatboxUploadError(RuntimeError):
    """Raised when a catbox.moe upload fails."""


def upload_to_catbox(image_bytes: bytes, filename: str = "image.jpg") -> str:
    """Upload bytes to catbox.moe anonymously and return the public HTTPS URL.

    catbox.moe accepts a multipart POST with `reqtype=fileupload` and returns the
    URL as plain text in the response body. No API key or signup required.
    Used wherever a public HTTPS URL is needed for content that is otherwise
    only available as in-process bytes (e.g. Instagram `image_url` publishing).
    """
    try:
        response = requests.post(
            CATBOX_API_URL,
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (filename, image_bytes, "image/jpeg")},
            timeout=60,
        )
    except requests.RequestException as exc:
        raise CatboxUploadError(f"catbox upload failed for {filename!r}: {exc}") from exc

    if response.status_code != 200:  # noqa: PLR2004
        raise CatboxUploadError(
            f"catbox upload failed for {filename!r}: HTTP {response.status_code} — {response.text[:200]}"
        )

    url = response.text.strip()
    if not url.startswith("https://"):
        raise CatboxUploadError(f"catbox returned unexpected response for {filename!r}: {url[:200]!r}")

    logger.debug(f"Uploaded {filename!r} to catbox: {url}")
    return url


def get_month_end(month_start: datetime.date) -> datetime.date:
    """Return the first day of the next month after ``month_start``."""
    if month_start.month == 12:  # noqa: PLR2004
        return month_start.replace(year=month_start.year + 1, month=1, day=1)
    return month_start.replace(month=month_start.month + 1, day=1)


def parse_month(value: str | None, default_to_next_month: bool = False) -> datetime.date:
    """
    Parse a month string into a date (first day of the month).

    Args:
        value: Date string in 'YYYY-MM' or 'YYYY-MM-DD' format, or None for default.
        default_to_next_month: If True and value is None, return next month.
                               If False and value is None, return current month.

    Returns:
        A date object representing the first day of the target month.

    Raises:
        ValueError: If the date format is invalid.
    """
    if value is None:
        today = datetime.date.today()  # noqa: DTZ011
        if default_to_next_month:
            return get_month_end(datetime.date(today.year, today.month, 1))
        return datetime.date(today.year, today.month, 1)

    value = value.strip()
    if len(value) == YYYY_MM_LENGTH:  # YYYY-MM
        return datetime.datetime.strptime(value, "%Y-%m").date()  # noqa: DTZ007
    if len(value) == YYYY_MM_DD_LENGTH:  # YYYY-MM-DD
        parsed = datetime.datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007
        return parsed.replace(day=1)
    raise ValueError(f"Invalid date format: {value}. Expected 'YYYY-MM' or 'YYYY-MM-DD'")


def parse_week(value: str | None, default_to_next_week: bool = False) -> datetime.date:
    """
    Parse a week string into a date (Monday of the week).

    Args:
        value: Date string in 'YYYY-MM-DD' format (must be a Monday), or None for default.
        default_to_next_week: If True and value is None, return next week's Monday.
                              If False and value is None, return current week's Monday.

    Returns:
        A date object representing the Monday of the target week.

    Raises:
        ValueError: If the date format is invalid or is not a Monday.
    """
    if value is None:
        today = datetime.date.today()  # noqa: DTZ011
        # Calculate current week's Monday (weekday 0 = Monday)
        days_since_monday = today.weekday()
        current_monday = today - datetime.timedelta(days=days_since_monday)
        if default_to_next_week:
            return current_monday + datetime.timedelta(weeks=1)
        return current_monday

    value = value.strip()
    if len(value) != YYYY_MM_DD_LENGTH:
        raise ValueError(f"Invalid date format: {value}. Expected 'YYYY-MM-DD' format (must be a Monday)")

    parsed = datetime.datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007

    # Validate that the date is a Monday (weekday 0)
    if parsed.weekday() != 0:
        day_name = parsed.strftime("%A")
        raise ValueError(f"Date {value} is a {day_name}, but must be a Monday")

    return parsed
