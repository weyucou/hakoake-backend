import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.pitzero.takeoff7.tokyo"
_SCHEDULE_PATH = "/events"
_MAX_EVENTS = 50


def _parse_ecard_date(text: str) -> str | None:
    """Parse date from ecard-date span text like '2026.6.17 WED' or '2026.6.17(WED)'."""
    match = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", text.strip())
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


@CrawlerRegistry.register("PitZeroCrawler")
class PitZeroCrawler(LiveHouseWebsiteCrawler):
    """
    Crawler for Shibuya PIT ZERO (https://www.pitzero.takeoff7.tokyo/).

    Schedule page uses query param: /events?date=YYYY%2FMM
    Site serves static HTML — no Playwright needed.
    """

    def extract_live_house_info(self, html_content: str) -> dict:
        return {
            "name": "Shibuya PIT ZERO",
            "name_kana": "シブヤピットゼロ",
            "name_romaji": "Shibuya Pit Zero",
            "address": "〒150-0042 東京都渋谷区宇田川町32-12 アソルティ渋谷B1F",
            "phone_number": "03-3770-7755",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        current_date = timezone.localdate()
        return f"{_BASE_URL}{_SCHEDULE_PATH}?date={current_date.year}%2F{current_date.month:02d}"

    def find_next_month_link(self, html_content: str) -> str | None:
        current_date = timezone.localdate()
        next_month = (current_date.month % 12) + 1
        next_year = current_date.year if next_month > current_date.month else current_date.year + 1
        return f"{_BASE_URL}{_SCHEDULE_PATH}?date={next_year}%2F{next_month:02d}"

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: PLR0912
        """Parse event cards from the schedule list page and enrich with detail-page times."""
        soup = self.create_soup(html_content)
        cards = soup.find_all("a", class_="ecard")
        logger.debug(f"Found {len(cards)} event cards on PitZero schedule page")

        schedules = []
        for card in cards[:_MAX_EVENTS]:
            try:
                schedule = self._parse_event_card(card)
                if not schedule:
                    continue
                detail_url = schedule.pop("_detail_url", None)
                if detail_url:
                    self._enrich_from_detail(schedule, detail_url)
                schedules.append(schedule)
            except Exception:  # noqa: BLE001
                logger.exception("Error parsing PitZero event card")

        logger.info(f"Extracted {len(schedules)} schedules from PitZero schedule page")
        return schedules

    def _parse_event_card(self, card: "Tag") -> dict | None:
        """Parse one <a class='ecard'> card into a schedule dict."""
        href = card.get("href", "")
        if not href:
            return None

        date_span = card.find("span", class_="ecard-date")
        if not date_span:
            return None
        date_str = _parse_ecard_date(date_span.get_text(strip=True))
        if not date_str:
            return None

        title_span = card.find("span", class_="ecard-title")
        event_name = title_span.get_text(strip=True) if title_span else None

        artists_span = card.find("span", class_="ecard-artists")
        performers: list[str] = []
        if artists_span:
            raw = artists_span.get_text(strip=True)
            performers = [p.strip() for p in re.split(r"\s*/\s*", raw) if p.strip()]

        img = card.find("img", class_="ecard-img")
        event_image_url = img["src"] if img and img.get("src") else None

        schedule: dict = {
            "date": date_str,
            "open_time": None,
            "start_time": None,
            "performers": performers,
            "_detail_url": urljoin(_BASE_URL, href),
        }
        if event_name:
            schedule["performance_name"] = event_name
        if event_image_url:
            schedule["event_image_url"] = event_image_url
        return schedule

    def _enrich_from_detail(self, schedule: dict, detail_url: str) -> None:
        """Fetch event detail page and add open/start times and refined artist list."""
        detail_html = self._fetch_event_detail_html(detail_url)
        if not detail_html:
            return

        soup = self.create_soup(detail_html)

        time_span = soup.find("span", class_="badge-time")
        if time_span:
            times = self._extract_open_start_times(time_span.get_text(strip=True))
            if times["open_time"]:
                schedule["open_time"] = times["open_time"]
            if times["start_time"]:
                schedule["start_time"] = times["start_time"]

        artist_nms = soup.find_all("span", class_="artist-nm")
        if artist_nms:
            schedule["performers"] = [nm.get_text(strip=True) for nm in artist_nms if nm.get_text(strip=True)]

        ticket_block = soup.find("div", class_="detail-ticket")
        if ticket_block:
            schedule["context"] = ticket_block.get_text(" ", strip=True)

    def _fetch_event_detail_html(self, detail_url: str) -> str | None:
        """Fetch detail page HTML, returning None on any failure."""
        try:
            return self.fetch_page(detail_url)
        except Exception:  # noqa: BLE001
            logger.warning(f"Failed to fetch PitZero detail page: {detail_url}")
            return None
