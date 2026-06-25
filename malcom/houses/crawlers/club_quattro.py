import logging
import re

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)

BASE_URL = "https://en.club-quattro.com/shibuya/schedule/"
TIME_PATTERN = re.compile(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})")


@CrawlerRegistry.register("ClubQuattroCrawler")
class ClubQuattroCrawler(LiveHouseWebsiteCrawler):
    """Crawler for Shibuya CLUB QUATTRO (https://en.club-quattro.com/shibuya/schedule/)."""

    def extract_live_house_info(self, html_content: str) -> dict:
        return {
            "name": "CLUB QUATTRO",
            "name_kana": "クラブクアトロ",
            "name_romaji": "CLUB QUATTRO",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        current = timezone.localdate()
        return f"{BASE_URL}?ym={current.year}{current.month:02d}"

    def find_next_month_link(self, html_content: str) -> str | None:
        soup = self.create_soup(html_content)
        year, month = self._extract_year_month(soup)
        if not year or not month:
            return None

        next_month = month + 1
        next_year = year
        if next_month > 12:  # noqa: PLR2004
            next_month = 1
            next_year += 1

        target_ym = f"{next_year}{next_month:02d}"
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if f"ym={target_ym}" in href:
                return href

        return None

    def extract_performance_schedules(self, html_content: str) -> list[dict]:
        soup = self.create_soup(html_content)
        year, month = self._extract_year_month(soup)
        if not year or not month:
            logger.warning("Could not extract year/month from Club Quattro schedule page")
            return []

        schedules = []
        for box in soup.find_all("div", class_="event-box"):
            schedule = self._parse_event_box(box, year, month)
            if schedule:
                schedules.append(schedule)

        logger.info(f"Extracted {len(schedules)} schedules from Club Quattro page ({year}-{month:02d})")
        return schedules

    def _extract_year_month(self, soup: BeautifulSoup) -> tuple[int | None, int | None]:
        year_tag = soup.find(class_="year")
        month_tag = soup.find(class_="month")
        try:
            return int(year_tag.get_text().strip()), int(month_tag.get_text().strip())
        except (AttributeError, ValueError):
            return None, None

    def _parse_event_box(self, box: BeautifulSoup, year: int, month: int) -> dict | None:
        day_tag = box.find("p", class_="day")
        if not day_tag:
            return None
        try:
            day = int(day_tag.get_text().strip())
        except ValueError:
            return None

        performers = self._extract_performers(box)
        if not performers:
            return None

        event_name_tag = box.find("p", class_="txt-02")
        event_name = event_name_tag.get_text().strip() if event_name_tag else None

        open_time, start_time = self._extract_times(box)

        return {
            "date": f"{year}-{month:02d}-{day:02d}",
            "open_time": open_time,
            "start_time": start_time,
            "performers": performers,
            "performance_name": event_name,
        }

    def _extract_performers(self, box: BeautifulSoup) -> list[str]:
        txt01 = box.find("p", class_="txt-01")
        if not txt01:
            return []
        hv_elm = txt01.find(class_="hv-elm")
        name = (hv_elm or txt01).get_text().strip()
        return [name] if name else []

    def _extract_times(self, box: BeautifulSoup) -> tuple[str | None, str | None]:
        detail_list = box.find("dl", class_="detail-list")
        if not detail_list:
            return None, None
        first_dd = detail_list.find("dd")
        if not first_dd:
            return None, None
        text = first_dd.get_text().strip()
        match = TIME_PATTERN.search(text)
        if match:
            return match.group(1), match.group(2)
        return None, None

    def fetch_next_month_schedules(self, html_content: str) -> list[dict]:
        next_url = self.find_next_month_link(html_content)
        if not next_url:
            return []
        try:
            next_html = self.fetch_page(next_url)
            return self.extract_performance_schedules(next_html)
        except requests.Timeout:
            logger.warning(f"Timeout fetching next-month Club Quattro page: {next_url}")
            return []
