import logging
import re

from bs4 import Tag
from django.utils import timezone

from .crawler import CrawlerRegistry
from .garret import DECEMBER, GarretCrawler

logger = logging.getLogger(__name__)

SCHEDULE_URL_TEMPLATE = "http://www.cyclone1997.com/schedule/{year}schedule_{month}.html"


@CrawlerRegistry.register("CycloneCrawler")
class CycloneCrawler(GarretCrawler):
    """Crawler for Shibuya CYCLONE (http://www.cyclone1997.com/schedule/).

    Same cyclone1997.com domain and HTML structure as GarretCrawler, but with a
    different URL path and `cyclone_day/` image directory.
    """

    def extract_live_house_info(self, html_content: str) -> dict:
        return {
            "name": "CYCLONE",
            "name_kana": "サイクロン",
            "name_romaji": "CYCLONE",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        current_date = timezone.localdate()
        return SCHEDULE_URL_TEMPLATE.format(year=current_date.year, month=current_date.month)

    def _extract_day_from_images(self, td: Tag) -> int | None:
        for img in td.find_all("img"):
            src = img.get("src", "")
            match = re.search(r"cyclone_day/(\d+)\.jpg", src)
            if match:
                return int(match.group(1))
        return None

    def find_next_month_link(self, html_content: str) -> str | None:
        soup = self.create_soup(html_content)
        current_year, current_month = self._extract_year_month(soup)
        if not current_year or not current_month:
            return None

        for link in soup.find_all("a", href=True):
            href = link["href"]
            match = re.search(r"(\d{4})schedule_(\d{1,2})\.html", href)
            if not match:
                continue

            link_year = int(match.group(1))
            link_month = int(match.group(2))

            if link_year == current_year and link_month == current_month + 1:
                return SCHEDULE_URL_TEMPLATE.format(year=link_year, month=link_month)
            if link_year == current_year + 1 and current_month == DECEMBER and link_month == 1:
                return SCHEDULE_URL_TEMPLATE.format(year=link_year, month=link_month)

        return None
