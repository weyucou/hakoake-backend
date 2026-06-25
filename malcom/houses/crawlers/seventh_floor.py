import logging
import re

from bs4 import BeautifulSoup
from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)

SCHEDULE_URL = "http://7th-floor.net/event/"


@CrawlerRegistry.register("SeventhFloorCrawler")
class SeventhFloorCrawler(LiveHouseWebsiteCrawler):
    """Crawler for Shibuya 7th Floor (http://7th-floor.net/event/).

    The page loads all historical events as div.eventList elements. Each element
    carries a CSS class in the format YYYY-M (e.g. 2026-6) for year-month matching.
    Date is in span.date as MM.DD, artists in ul.artists > li, event title in h2 span.evTit.
    """

    def extract_live_house_info(self, html_content: str) -> dict:
        return {
            "name": "7th Floor",
            "name_kana": "セブンスフロア",
            "name_romaji": "7th Floor",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        current = timezone.localdate()
        return f"{SCHEDULE_URL}?ym={current.year}-{current.month}"

    def find_next_month_link(self, html_content: str) -> str | None:
        """Construct next-month URL — the site loads all events on one page."""
        soup = self.create_soup(html_content)
        year, month = self._extract_target_year_month(soup)
        if not year or not month:
            return None
        next_month = month + 1
        next_year = year
        if next_month > 12:  # noqa: PLR2004
            next_month = 1
            next_year += 1
        return f"{SCHEDULE_URL}?ym={next_year}-{next_month}"

    def extract_performance_schedules(self, html_content: str) -> list[dict]:
        soup = self.create_soup(html_content)
        year, month = self._extract_target_year_month(soup)
        if not year or not month:
            logger.warning("Could not determine target year/month for 7th Floor schedule")
            return []

        target_class = f"{year}-{month}"
        schedules = []
        for div in soup.find_all("div", class_="eventList"):
            classes = div.get("class", [])
            if target_class not in classes:
                continue
            schedule = self._parse_event_div(div, year, month)
            if schedule:
                schedules.append(schedule)

        logger.info(f"Extracted {len(schedules)} schedules from 7th Floor page ({year}-{month:02d})")
        return schedules

    def _extract_target_year_month(self, soup: BeautifulSoup) -> tuple[int | None, int | None]:
        """Derive target year/month from the page URL embedded in the canonical link or from today."""
        canonical = soup.find("link", rel="canonical")
        if canonical:
            href = canonical.get("href", "")
            match = re.search(r"\?ym=(\d{4})-(\d{1,2})", href)
            if match:
                return int(match.group(1)), int(match.group(2))

        today = timezone.localdate()
        return today.year, today.month

    def _parse_event_div(self, div: BeautifulSoup, year: int, month: int) -> dict | None:
        date_span = div.find("span", class_="date")
        if not date_span:
            return None
        try:
            date_text = date_span.get_text().strip()
            month_part, day_part = date_text.split(".")
            if int(month_part) != month:
                return None
            day = int(day_part)
        except (ValueError, AttributeError):
            return None

        performers = self._extract_performers(div)
        if not performers:
            return None

        ev_tit = div.find("span", class_="evTit")
        event_name = ev_tit.get_text().strip() if ev_tit else None

        return {
            "date": f"{year}-{month:02d}-{day:02d}",
            "open_time": None,
            "start_time": None,
            "performers": performers,
            "performance_name": event_name,
        }

    def _extract_performers(self, div: BeautifulSoup) -> list[str]:
        artists_ul = div.find("ul", class_="artists")
        if not artists_ul:
            return []
        performers = []
        for li in artists_ul.find_all("li"):
            text = li.get_text().strip()
            if text:
                performers.append(text)
        return performers
