import logging
import re

from bs4 import BeautifulSoup
from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)

SCHEDULE_URL_TEMPLATE = "https://shinjuku-face.com/event/date/{year}/{month:02d}"
TIME_PATTERN = re.compile(r"(\d{1,2}:\d{2})\s*[/／]\s*(\d{1,2}:\d{2})")


@CrawlerRegistry.register("ShinjukuFaceCrawler")
class ShinjukuFaceCrawler(LiveHouseWebsiteCrawler):
    """Crawler for Shinjuku FACE (https://shinjuku-face.com/event/date/{year}/{month:02d})."""

    def extract_live_house_info(self, html_content: str) -> dict:
        return {
            "name": "Shinjuku FACE",
            "name_kana": "シンジュクフェイス",
            "name_romaji": "Shinjuku FACE",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        current = timezone.localdate()
        return SCHEDULE_URL_TEMPLATE.format(year=current.year, month=current.month)

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

        target_url = SCHEDULE_URL_TEMPLATE.format(year=next_year, month=next_month)
        for a in soup.find_all("a", href=True):
            if a["href"] == target_url:
                return target_url

        return None

    def extract_performance_schedules(self, html_content: str) -> list[dict]:
        soup = self.create_soup(html_content)
        year, month = self._extract_year_month(soup)
        if not year or not month:
            logger.warning("Could not extract year/month from Shinjuku FACE schedule page")
            return []

        schedules = []
        for article in soup.find_all("article"):
            schedule = self._parse_article(article, year, month)
            if schedule:
                schedules.append(schedule)

        logger.info(f"Extracted {len(schedules)} schedules from Shinjuku FACE page ({year}-{month:02d})")
        return schedules

    def _extract_year_month(self, soup: BeautifulSoup) -> tuple[int | None, int | None]:
        year_tag = soup.find(class_="eventkijiyear")
        month_tag = soup.find(class_="eventkijimonth")
        try:
            # Year text may have trailing punctuation, e.g. "2026．"
            year_text = re.sub(r"\D", "", year_tag.get_text())
            month_text = month_tag.get_text().strip()
            return int(year_text), int(month_text)
        except (AttributeError, ValueError):
            return None, None

    def _parse_article(self, article: BeautifulSoup, year: int, month: int) -> dict | None:
        day_tag = article.find(class_="day")
        if not day_tag:
            return None
        try:
            day = int(day_tag.get_text().strip())
        except ValueError:
            return None

        performers = self._extract_performers(article)
        if not performers:
            return None

        title_tag = article.find(class_="title_title")
        event_name = None
        if title_tag:
            a = title_tag.find("a")
            event_name = (a or title_tag).get_text().strip() or None

        open_time, start_time = self._extract_times(article)

        return {
            "date": f"{year}-{month:02d}-{day:02d}",
            "open_time": open_time,
            "start_time": start_time,
            "performers": performers,
            "performance_name": event_name,
        }

    def _extract_performers(self, article: BeautifulSoup) -> list[str]:
        lineup = article.find(class_="title_lineup")
        if not lineup:
            return []
        a = lineup.find("a")
        name = (a or lineup).get_text().strip()
        return [name] if name else []

    def _extract_times(self, article: BeautifulSoup) -> tuple[str | None, str | None]:
        detail = article.find("dl", class_="eventlist-detail")
        if not detail:
            return None, None
        dd = detail.find("dd")
        if not dd:
            return None, None
        match = TIME_PATTERN.search(dd.get_text())
        if match:
            return match.group(1), match.group(2)
        return None, None
