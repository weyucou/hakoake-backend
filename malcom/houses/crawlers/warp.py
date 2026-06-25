import logging
import re

from bs4 import BeautifulSoup
from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)

BASE_URL = "http://warp.rinky.info/"
SCHEDULE_LINK_PATTERN = re.compile(r"/schedules/(\d{4}-\d{2})/(\d+)\.html$")
DATE_TITLE_PATTERN = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")
PERFORMER_SKIP_PATTERN = re.compile(r"^and more\.{0,3}$", re.IGNORECASE)
TIME_PATTERN = re.compile(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})")


@CrawlerRegistry.register("WarpCrawler")
class WarpCrawler(LiveHouseWebsiteCrawler):
    """Crawler for Kichijoji WARP (http://warp.rinky.info/).

    The homepage lists upcoming events as article[data-aos] elements linking to
    individual event pages at /schedules/YYYY-MM/ID.html. Each event page contains
    date (in <title>), performers (in div.w-flyer), and times (in span.strong).
    """

    def extract_live_house_info(self, html_content: str) -> dict:
        return {
            "name": "WARP",
            "name_kana": "ワープ",
            "name_romaji": "WARP",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        return BASE_URL

    def find_next_month_link(self, html_content: str) -> str | None:
        """WARP uses one rolling homepage; return the same URL for continuity."""
        return BASE_URL

    def extract_performance_schedules(self, html_content: str) -> list[dict]:
        """Extract schedules from the WARP homepage by following event detail links."""
        soup = self.create_soup(html_content)
        current = timezone.localdate()
        target_ym = f"{current.year}-{current.month:02d}"

        event_urls = self._extract_event_urls(soup, target_ym)
        schedules = []
        for url in event_urls:
            schedule = self._fetch_and_parse_event(url)
            if schedule:
                schedules.append(schedule)

        logger.info(f"Extracted {len(schedules)} schedules from WARP ({target_ym})")
        return schedules

    def _extract_event_urls(self, soup: BeautifulSoup, target_ym: str) -> list[str]:
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            match = SCHEDULE_LINK_PATTERN.search(href)
            if match and match.group(1) == target_ym:
                urls.append(href)
        return list(dict.fromkeys(urls))

    def _fetch_and_parse_event(self, url: str) -> dict | None:
        try:
            html = self.fetch_page(url)
        except OSError as exc:
            logger.warning(f"Failed to fetch WARP event page {url}: {exc}")
            return None
        return self._parse_event_page(html, url)

    def _parse_event_page(self, html_content: str, url: str) -> dict | None:
        soup = self.create_soup(html_content)

        title_tag = soup.find("title")
        if not title_tag:
            return None
        date_match = DATE_TITLE_PATTERN.search(title_tag.get_text())
        if not date_match:
            return None
        date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        detail = soup.find("section", class_="schedules-detail")
        if not detail:
            return None

        h4 = detail.find("h4")
        event_name = h4.get_text(separator=" ").strip() if h4 else None

        performers = self._extract_performers(detail)
        if not performers:
            return None

        open_time, start_time = self._extract_times(detail)

        return {
            "date": date_str,
            "open_time": open_time,
            "start_time": start_time,
            "performers": performers,
            "performance_name": event_name,
        }

    def _extract_performers(self, detail: BeautifulSoup) -> list[str]:
        w_flyer = detail.find("div", class_="w-flyer")
        if not w_flyer:
            return []
        for br in w_flyer.find_all("br"):
            br.replace_with("\n")
        lines = w_flyer.get_text().split("\n")
        performers = []
        for line in lines:
            name = line.strip()
            if not name or PERFORMER_SKIP_PATTERN.match(name):
                continue
            performers.append(name)
        return performers

    def _extract_times(self, detail: BeautifulSoup) -> tuple[str | None, str | None]:
        notes = detail.find("section", class_="notes-wrapper")
        if not notes:
            return None, None
        strong = notes.find("span", class_="strong")
        if not strong:
            return None, None
        match = TIME_PATTERN.search(strong.get_text())
        if match:
            return match.group(1), match.group(2)
        return None, None
