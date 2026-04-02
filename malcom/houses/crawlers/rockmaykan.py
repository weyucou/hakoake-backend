import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)


@CrawlerRegistry.register("RockmaykanCrawler")
class RockmaykanCrawler(LiveHouseWebsiteCrawler):
    """
    Specialized crawler for Rockmaykan website (https://www.rockmaykan.com).

    Handles the specific structure of Rockmaykan's schedule page including:
    - Event listings with date format (YYYY年M月D日)
    - Performer extraction from event descriptions
    - Time format (開場/開演 times)
    - Ticket information
    """

    def find_schedule_link(self, html_content: str) -> str | None:
        """Find the schedule link for Rockmaykan website."""
        # Rockmaykan has monthly schedule pages accessible from /plan-02
        # First, fetch the plan-02 page to find the current month link
        plan_page_url = urljoin(self.base_url, "/plan-02")

        try:
            plan_html = self.fetch_page(plan_page_url)
            soup = self.create_soup(plan_html)

            # Calculate current month with year-aware logic
            current_date = timezone.localdate()
            year = current_date.year
            month = current_date.month

            # Look for links with format {YEAR}年{MONTH}月
            target_pattern = f"{year}年{month}月"
            logger.debug(f"Looking for Rockmaykan current month link with pattern: {target_pattern}")

            # Check all links for the date pattern
            links = soup.find_all("a", href=True)
            for link in links:
                href = link.get("href", "")
                text = link.get_text(strip=True)

                # Skip javascript and anchors
                if not href or href.startswith(("#", "javascript:")):
                    continue

                # Check if the link text or href contains the date pattern
                if target_pattern in text or target_pattern in href:
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found current month link for Rockmaykan: {full_url}")
                    return full_url

            # If no current month link found, return the plan-02 page itself
            logger.debug(f"No current month link found, using plan-02 page: {plan_page_url}")
            return plan_page_url  # noqa: TRY300

        except Exception:  # noqa: BLE001
            logger.exception("Error finding schedule link for Rockmaykan")
            # Fallback to /plan-02
            return urljoin(self.base_url, "/plan-02")

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performance schedules from Rockmaykan's website.

        Handles the specific structure:
        - Events with date format like "2025年8月18日"
        - Performer names from event descriptions
        - Event names and times
        """
        schedules = []
        soup = self.create_soup(html_content)

        try:
            # Look for event containers or monthly schedule links
            monthly_links = soup.find_all("a", href=re.compile(r"\d{4}年\d{1,2}月", re.IGNORECASE))

            # Process current page first
            schedules = self._parse_rockmaykan_events(soup)

            # Try to fetch monthly schedules
            for link in monthly_links[:2]:  # Limit to 2 months
                try:
                    monthly_url = urljoin(self.base_url, link.get("href"))
                    monthly_content = self.fetch_page(monthly_url)
                    monthly_soup = self.create_soup(monthly_content)
                    monthly_schedules = self._parse_rockmaykan_events(monthly_soup)
                    schedules.extend(monthly_schedules)
                except Exception as e:  # noqa: BLE001
                    logger.debug(f"Failed to fetch monthly schedule {link}: {e}")
                    continue

            # Limit to reasonable number of events
            MAX_EVENTS = 30  # noqa: N806
            schedules = schedules[:MAX_EVENTS]

            logger.info(f"Extracted {len(schedules)} schedules from Rockmaykan website")

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting Rockmaykan schedules")
            return []
        else:
            return schedules

    def _parse_rockmaykan_events(self, soup: "Tag") -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse events from Rockmaykan page content."""
        schedules = []

        # Extract year from page content
        current_date = timezone.localdate()
        year = current_date.year

        # Look for year in page content
        year_match = soup.find(text=re.compile(r"(\d{4})年"))
        if year_match:
            year_search = re.search(r"(\d{4})年", str(year_match))
            if year_search:
                year = int(year_search.group(1))

        # Find all H4 event headers with class "design-tmpl h4-cute-green"
        h4_elements = soup.find_all("h4", class_="design-tmpl h4-cute-green")
        logger.debug(f"Found {len(h4_elements)} H4 event headers")

        for h4 in h4_elements[:30]:  # Limit to 30 events
            try:
                schedule = self._parse_rockmaykan_event_block(h4, year)
                if schedule:
                    schedules.append(schedule)
            except Exception:  # noqa: BLE001
                logger.exception("Error parsing Rockmaykan event block")
                continue

        return schedules

    def _parse_rockmaykan_event_block(self, h4_element: "Tag", year: int) -> dict | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse a single Rockmaykan event block (H4 + table)."""
        # Extract date and event name from H4 text
        # Format: "MM月DD日（曜）Event Name" or just "MM月DD日（曜）"
        h4_text = h4_element.get_text(strip=True)

        # Extract date (MM月DD日)
        date_match = re.search(r"(\d{1,2})月(\d{1,2})日", h4_text)
        if not date_match:
            return None

        month = int(date_match.group(1))
        day = int(date_match.group(2))
        date_str = f"{year:04d}-{month:02d}-{day:02d}"

        # Extract event name (everything after the date pattern)
        event_name = None
        event_match = re.search(r"\d{1,2}月\d{1,2}日[（(][^)）]+[)）]\s*(.+)", h4_text)
        if event_match:
            event_name = event_match.group(1).strip()

        # Find the table immediately following this H4
        table = h4_element.find_next_sibling("table", class_="table table-bordered")
        if not table:
            # Try finding next table without class restriction
            table = h4_element.find_next("table")

        if not table:
            logger.debug(f"No table found for event on {date_str}")
            return None

        # Extract performers from table
        performers = []
        performer_row = None

        # Find row with "出演" label
        for row in table.find_all("tr"):
            label_cell = row.find("td")
            if label_cell and "出演" in label_cell.get_text():
                performer_row = row
                break

        if performer_row:
            # Get the second td (performer data)
            cells = performer_row.find_all("td")
            if len(cells) >= 2:  # noqa: PLR2004
                performer_cell = cells[1]

                # Extract performers from <p> tags
                p_tags = performer_cell.find_all("p")
                if p_tags:
                    for p in p_tags:
                        performer = p.get_text(strip=True)
                        # Clean and validate
                        performer = self._clean_rockmaykan_performer(performer)
                        if performer and len(performer) >= 2:  # noqa: PLR2004
                            performers.append(performer)
                else:
                    # No <p> tags, try splitting text
                    text = performer_cell.get_text(strip=True)
                    parts = re.split(r"[/／\n]", text)
                    for part in parts:
                        performer = self._clean_rockmaykan_performer(part)
                        if performer and len(performer) >= 2:  # noqa: PLR2004
                            performers.append(performer)

        # Extract times from table
        open_time = "18:30"
        start_time = "19:00"

        for row in table.find_all("tr"):
            label_cell = row.find("td")
            if label_cell:
                label_text = label_cell.get_text(strip=True)
                if "開場" in label_text or "開演" in label_text:
                    cells = row.find_all("td")
                    if len(cells) >= 2:  # noqa: PLR2004
                        time_text = cells[1].get_text(strip=True)
                        # Extract times from format: "開場13:30/開演14:00"
                        time_match = re.search(
                            r"開場\s*[:：]?\s*(\d{1,2}[:：]\d{2})\s*[/／]*\s*開演\s*[:：]?\s*(\d{1,2}[:：]\d{2})",
                            time_text,
                        )
                        if time_match:
                            open_time = time_match.group(1).replace("：", ":")
                            start_time = time_match.group(2).replace("：", ":")
                    break

        if not performers:
            logger.debug(f"No performers found for event on {date_str}")
            return None

        schedule: dict = {
            "date": date_str,
            "open_time": open_time,
            "start_time": start_time,
            "performers": performers[:8],
            "performance_name": event_name,
        }
        # Look for event image in the H4 or adjacent siblings
        for sibling in [h4_element, table]:
            img = sibling.find("img", src=True) if sibling else None
            if img:
                schedule["event_image_url"] = urljoin(self.base_url, img["src"])
                break
        return schedule

    def _clean_rockmaykan_performer(self, name: str) -> str:
        """Clean a Rockmaykan performer name."""
        if not name:
            return ""

        name = name.strip()

        # Remove bracketed content
        name = re.sub(r"【.*?】", "", name)
        name = re.sub(r"\\[.*?\\]", "", name)
        name = re.sub(r"\\(.*?\\)", "", name)
        name = re.sub(r"（.*?）", "", name)

        # Remove "with" and similar connectors
        name = re.sub(r"\\s+with\\s+.*", "", name, flags=re.IGNORECASE)

        # Skip obvious non-performer patterns
        skip_patterns = [
            r"^\\d+$",  # Pure numbers
            r"^[¥￥]\\d+",  # Price
            r"\\d{1,2}:\\d{2}",  # Time
            r"^(OPEN|START|CLOSE|開場|開演)$",
            r"^(チケット|ticket|予約|問い合わせ)$",
            r"^(drink|1drink|ドリンク)$",
            r"^(前売|当日|advance|door)$",
            r"^(説明|出演|ゲスト|Guest)[:：]",  # Labels
        ]

        for pattern in skip_patterns:
            if re.search(pattern, name, re.IGNORECASE):
                return ""

        return name.strip()

    def _extract_rockmaykan_performers(self, event_text: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performer names from Rockmaykan event text.

        Handles patterns like:
        - 出演: performer list
        - Artist names separated by various delimiters
        - Multiple performers listed line by line
        """
        performers = []

        # Look for performer sections with various patterns
        performer_patterns = [
            r"(?:出演|LIVE|ライブ|Artist|アーティスト)[:：\s]*([^\n\r]+)",
            r"【([^】]+)】",  # Content in 【】 brackets
            r"■([^■\n]+)",  # Bullet point content
        ]

        for pattern in performer_patterns:
            matches = re.findall(pattern, event_text, re.IGNORECASE)
            for match in matches:
                # Split by common delimiters
                names = re.split(r"[,、／/・&×\n\r]", match)
                for raw_name in names:
                    name = raw_name.strip()
                    if self._is_likely_rockmaykan_performer(name):
                        cleaned_name = self._clean_performer_name(name)
                        if cleaned_name and self._is_valid_performer_name(cleaned_name):
                            performers.append(cleaned_name)

        # If no patterns found, look for known performers in lines
        if not performers:
            lines = event_text.split("\n")
            for line in lines[:15]:  # Check first 15 lines
                line = line.strip()  # noqa: PLW2901
                if self._is_likely_rockmaykan_performer(line):
                    cleaned_name = self._clean_performer_name(line)
                    if cleaned_name and self._is_valid_performer_name(cleaned_name):
                        performers.append(cleaned_name)

        # Remove duplicates while preserving order
        seen = set()
        unique_performers = []
        for performer in performers:
            if performer.lower() not in seen:
                seen.add(performer.lower())
                unique_performers.append(performer)

        return unique_performers[:8]  # Limit to 8 performers

    def _is_likely_rockmaykan_performer(self, text: str) -> bool:
        """Check if text is likely a performer name in Rockmaykan context."""
        MIN_TEXT_LENGTH = 2  # noqa: N806
        MAX_TEXT_LENGTH = 100  # noqa: N806
        if not text or len(text.strip()) < MIN_TEXT_LENGTH or len(text) > MAX_TEXT_LENGTH:
            return False

        text = text.strip()

        # Skip obvious non-performer patterns
        skip_patterns = [
            r"^\d+$",  # Pure numbers
            r"^[¥￥]\d+",  # Price
            r"\d{1,2}:\d{2}",  # Time
            r"^(OPEN|START|CLOSE|開場|開演)$",
            r"^(チケット|ticket|予約|問い合わせ)$",
            r"^(※|注意|info|information).*",
            r"^(drink|1drink|ドリンク)$",
            r"^(前売|当日|advance|door)$",
            r"^(目黒|鹿鳴館|Rockmaykan)$",  # Venue names
            r"TEL|FAX|tel|fax",
            r"http|www\.",
            r"^\d{4}年\d{1,2}月\d{1,2}日",  # Date only
            r"^(イープラス|Tiget|チケット販売)$",  # Ticket platforms
        ]

        for pattern in skip_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        # Must contain meaningful characters
        return bool(re.search(r"[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", text))

    def _extract_rockmaykan_event_name(self, event_text: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event name from Rockmaykan event text."""
        # Look for event names in quotes or special formatting
        title_patterns = [
            r"『([^』]+)』",  # Japanese quotes
            r"「([^」]+)」",  # Japanese quotes
            r'"([^"]+)"',  # Regular quotes
            r"'([^']+)'",  # Single quotes
            r"【([^】]+)】",  # Special brackets (but check it's not performer list)
            r"■([^■\n]+)",  # Bullet point titles
        ]

        for pattern in title_patterns:
            matches = re.findall(pattern, event_text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    title = match[0].strip()
                else:
                    title = match.strip()

                MIN_TITLE_LENGTH = 3  # noqa: N806
                MAX_TITLE_LENGTH = 100  # noqa: N806
                if MIN_TITLE_LENGTH < len(title) <= MAX_TITLE_LENGTH:  # noqa: SIM102
                    # Skip if it looks like a performer list
                    if not re.search(r"(出演|LIVE|ライブ|Artist)", title):
                        return title

        return None

    def _extract_rockmaykan_times(self, event_text: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract open and start times from Rockmaykan event text."""
        # Default times
        times = {"open_time": "18:30", "start_time": "19:00"}

        # Look for Rockmaykan time patterns
        time_patterns = [
            r"開場\s*[:：]?\s*(\d{1,2}[:：]\d{2})\s*[/\s]*開演\s*[:：]?\s*(\d{1,2}[:：]\d{2})",
            r"OPEN\s*[:：]?\s*(\d{1,2}[:：]\d{2})\s*[/\s]*START\s*[:：]?\s*(\d{1,2}[:：]\d{2})",
            r"(\d{1,2}[:：]\d{2})\s*/\s*(\d{1,2}[:：]\d{2})",
        ]

        for pattern in time_patterns:
            match = re.search(pattern, event_text, re.IGNORECASE)
            if match:
                # Normalize time format (replace ： with :)
                open_time = match.group(1).replace("：", ":")
                start_time = match.group(2).replace("：", ":")
                times["open_time"] = open_time
                times["start_time"] = start_time
                break

        return times

    def find_next_month_link(self, html_content: str) -> str | None:
        """Find next month link for Rockmaykan website."""
        soup = self.create_soup(html_content)

        # Calculate next month with year-aware logic
        current_date = timezone.localdate()
        next_month = (current_date.month % 12) + 1
        next_year = current_date.year if next_month > current_date.month else current_date.year + 1

        # Rockmaykan uses Japanese date format in links: {YEAR}年{MONTH}月
        # Search for links containing this pattern
        target_pattern = f"{next_year}年{next_month}月"
        logger.debug(f"Looking for Rockmaykan next month link with pattern: {target_pattern}")

        # Check all links for the date pattern
        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True)

            # Skip javascript and anchors
            if not href or href.startswith(("#", "javascript:")):
                continue

            # Check if the link text or href contains the date pattern
            if target_pattern in text or target_pattern in href:
                full_url = urljoin(self.base_url, href)
                logger.debug(f"Found next month link for Rockmaykan: {full_url}")
                return full_url

        logger.debug("No next month link found for Rockmaykan")
        return None
