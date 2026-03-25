import logging
import re

from bs4 import BeautifulSoup, Tag
from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)

SCHEDULE_URL_TEMPLATE = "http://www.cyclone1997.com/garret/g_schedule/garret_{year}schedule_{month}.html"

DECEMBER = 12

# Patterns to skip as non-performer content
SKIP_PATTERNS = re.compile(
    r"^INFORMATION COMING SOON|^and more|^TBA$",
    re.IGNORECASE,
)


@CrawlerRegistry.register("GarretCrawler")
class GarretCrawler(LiveHouseWebsiteCrawler):
    """Crawler for Garret website (http://www.cyclone1997.com/garret/)."""

    def fetch_page(self, url: str) -> str:
        """Override to handle Shift-JIS encoding."""
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = "shift_jis"
        return response.text

    def extract_live_house_info(self, html_content: str) -> dict:
        """Extract live house info - hardcoded for Garret."""
        return {
            "name": "GARRET",
            "name_kana": "ギャレット",
            "name_romaji": "GARRET",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        """Construct current month schedule URL."""
        current_date = timezone.localdate()
        return SCHEDULE_URL_TEMPLATE.format(year=current_date.year, month=current_date.month)

    def extract_performance_schedules(self, html_content: str) -> list[dict]:
        """Extract schedules from Garret's table-based layout."""
        soup = self.create_soup(html_content)

        year, month = self._extract_year_month(soup)
        if not year or not month:
            logger.warning("Could not extract year/month from Garret schedule page")
            return []

        schedules = []
        for table in soup.find_all("table"):
            schedule = self._parse_event_table(table, year, month)
            if schedule:
                schedules.append(schedule)

        logger.info(f"Extracted {len(schedules)} schedules from Garret page ({year}-{month:02d})")
        return schedules

    def _extract_year_month(self, soup: BeautifulSoup) -> tuple[int | None, int | None]:
        """Extract year and month from header like '2026.<strong>3 March</strong>'."""
        body_text = soup.get_text()
        match = re.search(r"(\d{4})\.\s*(\d{1,2})\s*[A-Za-z]+", body_text)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None

    def _parse_event_table(self, table: Tag, year: int, month: int) -> dict | None:
        """Parse a single event table into a schedule dict."""
        tds = table.find_all("td")
        if len(tds) < 2:  # noqa: PLR2004
            return None

        left_td, right_td = tds[0], tds[1]

        # Extract day from image filename: garret_day/DD.jpg
        day = self._extract_day_from_images(left_td)
        if not day:
            return None

        date_str = f"{year}-{month:02d}-{day:02d}"

        # Extract performers from <strong> tags within the right td
        performers = self._extract_performers(right_td)
        if not performers:
            return None

        # Extract event name (text before the performer strong tags)
        event_name = self._extract_event_name(right_td)

        # Extract times from right td text (Garret uses "|" separator)
        right_text = right_td.get_text()
        times = self._extract_garret_times(right_text)

        return {
            "date": date_str,
            "open_time": times.get("open_time"),
            "start_time": times.get("start_time"),
            "performers": performers,
            "performance_name": event_name,
        }

    def _extract_day_from_images(self, td: Tag) -> int | None:
        """Extract day number from garret_day image filename."""
        for img in td.find_all("img"):
            src = img.get("src", "")
            match = re.search(r"garret_day/(\d+)\.jpg", src)
            if match:
                return int(match.group(1))
        return None

    def _extract_performers(self, td: Tag) -> list[str]:
        """Extract performer names from <strong> tags in the right column.

        "X PRESENTS" entries are event names (not performers) and are skipped.
        """
        performers = []

        for strong in td.find_all("strong"):
            # Get text with <br> replaced by newlines
            for br in strong.find_all("br"):
                br.replace_with("\n")
            text = strong.get_text()

            # Skip entire strong block if it's a PRESENTS-only event name
            stripped = re.sub(r"\n", " ", text).strip()
            if re.search(r"\bPRESENTS\s*$", stripped, re.IGNORECASE):
                continue

            # Split by common delimiters: /, newline
            parts = re.split(r"\s*/\s*|\n", text)
            for part in parts:
                name = part.strip()
                if not name:
                    continue
                if SKIP_PATTERNS.search(name):
                    continue
                if name not in performers:
                    performers.append(name)

        return performers

    def _extract_garret_times(self, text: str) -> dict[str, str | None]:
        """Extract OPEN/START times from Garret format: 'OPEN HH:MM | START HH:MM'."""
        result: dict[str, str | None] = {"open_time": None, "start_time": None}
        pattern = r"OPEN\s+(\d{1,2}:\d{2})\s*\|\s*START\s+(\d{1,2}:\d{2})"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["open_time"] = match.group(1)
            result["start_time"] = match.group(2)
        return result

    def _extract_event_name(self, td: Tag) -> str | None:
        """Extract event name from text before the performer strong tags."""
        # Get the outer span (font-size: 10px) text content
        span = td.find("span", style=re.compile(r"font-size:\s*10px"))
        if not span:
            return None

        # Walk through children to find text before the first font-size: 14px span
        event_parts = []
        for child in span.children:
            # Stop when we hit the performer span/strong area
            if isinstance(child, Tag):
                if child.find("span", style=re.compile(r"font-size:\s*14px")):
                    break
                if child.find("strong"):
                    break
            else:
                text = str(child).strip()
                if text:
                    event_parts.append(text)

        name = " ".join(event_parts).strip()
        # Clean up common noise
        name = re.sub(r"^pre\.\s*", "", name, flags=re.IGNORECASE).strip()
        return name if name else None

    def find_next_month_link(self, html_content: str) -> str | None:
        """Find next month schedule URL from navigation links."""
        soup = self.create_soup(html_content)

        # Look for links matching the schedule URL pattern
        for link in soup.find_all("a", href=True):
            href = link["href"]
            match = re.search(r"garret_(\d{4})schedule_(\d{1,2})\.html", href)
            if not match:
                continue

            link_year = int(match.group(1))
            link_month = int(match.group(2))

            # Find the current page's year/month to identify "next"
            current_year, current_month = self._extract_year_month(soup)
            if not current_year or not current_month:
                continue

            # Check if this link is for the next month
            if link_year == current_year and link_month == current_month + 1:
                return SCHEDULE_URL_TEMPLATE.format(year=link_year, month=link_month)
            if link_year == current_year + 1 and current_month == DECEMBER and link_month == 1:
                return SCHEDULE_URL_TEMPLATE.format(year=link_year, month=link_month)

        return None
