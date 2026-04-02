import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)

MIN_PERFORMER_NAME_LENGTH = 2
MAX_PERFORMER_NAME_LENGTH = 50


@CrawlerRegistry.register("ShinjukuMarbleCrawler")
class ShinjukuMarbleCrawler(LiveHouseWebsiteCrawler):
    """
    Specialized crawler for Shinjuku Marble website (https://shinjuku-marble.com/).

    Handles the specific structure of Shinjuku Marble's schedule page including:
    - Event listings with date format (YYYY/M/D(曜日))
    - Performer extraction from [出演] sections
    - Time format (OPEN HH:MM / START HH:MM)
    - Ticket information (前売り/当日 prices)
    """

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901
        """
        Extract performance schedules from Shinjuku Marble's website.

        Handles the specific structure:
        - Events with date format like "2025/9/7(日)"
        - [出演] sections for performers
        - Time format "OPEN 19:30 / START 20:00"
        - Event names and descriptions
        - Uses Playwright to handle "Load More" button for complete event list
        """
        schedules = []

        try:
            # Find schedule URL from the main page
            schedule_url = self.find_schedule_link(html_content)
            if not schedule_url:
                logger.warning("No schedule URL found")
                return []

            # Fetch schedule page with JavaScript (to handle "Load More" button)
            logger.debug("Fetching schedule page with Playwright to load all events")
            schedule_html = self.fetch_page_js(
                schedule_url,
                wait_for_selector=".mec-event-description",  # Wait for event descriptions to load
                click_load_more=True,
                load_more_selector=".mec-load-more-button",  # Can be div or button element
                max_clicks=30,  # Allow up to 30 clicks to load all November events
            )

            soup = self.create_soup(schedule_html)

            # Find all "View Detail" links - these lead to event detail pages
            detail_links = []
            for link in soup.find_all("a", href=True):
                if "View Detail" in link.get_text() or "詳細" in link.get_text():
                    href = link.get("href")
                    if href and not href.startswith("#"):
                        detail_links.append(urljoin(self.base_url, href))

            logger.info(f"Found {len(detail_links)} detail page links after loading all events")

            # Fetch each detail page and extract event information
            for detail_url in detail_links[:30]:  # Limit to 30 events
                try:
                    detail_html = self.fetch_page(detail_url)
                    if detail_html:
                        schedule = self._extract_from_detail_page(detail_html)
                        if schedule:
                            schedules.append(schedule)
                            logger.debug(f"✓ Extracted event: {schedule['date']} - {schedule['performers']}")
                        else:
                            logger.warning(f"✗ Failed to extract schedule from detail page: {detail_url}")
                except Exception:  # noqa: BLE001
                    logger.exception(f"Failed to fetch detail page: {detail_url}")
                    continue

            logger.info(f"Extracted {len(schedules)} schedules from Shinjuku Marble website")

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting Shinjuku Marble schedules")
            return []
        else:
            return schedules

    def _parse_json_ld_event(self, event_data: dict) -> dict | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse a JSON-LD event object."""
        try:
            # Extract date
            start_date = event_data.get("startDate", "")
            if not start_date:
                return None

            # Parse date
            date_obj = datetime.fromisoformat(start_date)
            date_str = date_obj.strftime("%Y-%m-%d")

            # Extract performers
            performers = []
            if "performer" in event_data:
                performer_data = event_data["performer"]
                if isinstance(performer_data, list):
                    for p in performer_data:
                        if isinstance(p, dict) and "name" in p:
                            performers.append(p["name"])
                        elif isinstance(p, str):
                            performers.append(p)
                elif isinstance(performer_data, dict) and "name" in performer_data:
                    performers.append(performer_data["name"])
                elif isinstance(performer_data, str):
                    performers.append(performer_data)

            # Extract event name
            event_name = event_data.get("name", "")

            # Extract times (default if not found)
            open_time = "18:30"
            start_time = "19:00"

            # Try to extract from doorTime and startDate
            if "doorTime" in event_data:
                door_time = datetime.fromisoformat(event_data["doorTime"])
                open_time = door_time.strftime("%H:%M")

            start_datetime = datetime.fromisoformat(start_date)
            start_time = start_datetime.strftime("%H:%M")

            if performers:
                return {
                    "date": date_str,
                    "open_time": open_time,
                    "start_time": start_time,
                    "performers": performers,
                    "performance_name": event_name,
                }

        except Exception:  # noqa: BLE001
            logger.exception("Error parsing JSON-LD event")

        return None

    def _parse_html_events(self, soup: "Tag") -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse events from HTML content."""
        schedules = []

        # Look for event containers with various possible classes
        soup.find_all(["div", "article"], class_=re.compile(r"event|schedule|live|ライブ", re.IGNORECASE))

        # Also look for date patterns in the text
        text = soup.get_text()

        # Shinjuku Marble date pattern: YYYY/M/D(曜日) format
        date_pattern = r"(\d{4})/(\d{1,2})/(\d{1,2})\s*\([^)]+\)"
        date_matches = list(re.finditer(date_pattern, text))

        for match in date_matches[:30]:  # Limit to 30 events
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))

            # Extract event content after this date
            start_pos = match.end()

            # Find the next date or take next 1000 chars
            next_date_match = re.search(date_pattern, text[start_pos:])
            if next_date_match:
                end_pos = start_pos + next_date_match.start()
                event_content = text[start_pos:end_pos]
            else:
                event_content = text[start_pos : start_pos + 1000]

            # Extract performers and event info
            performers = self._extract_marble_performers(event_content)
            event_name = self._extract_marble_event_name(event_content)
            times = self._extract_marble_times(event_content)

            if performers:
                schedule_data = {
                    "date": f"{year:04d}-{month:02d}-{day:02d}",
                    "open_time": times["open_time"],
                    "start_time": times["start_time"],
                    "performers": performers,
                    "performance_name": event_name,
                }
                schedules.append(schedule_data)

                logger.debug(f"Extracted Marble event: {schedule_data['date']} - {performers}")

        return schedules

    def _extract_marble_performers(self, event_text: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performer names from Shinjuku Marble event text.

        Handles patterns like:
        - "[出演]" followed by performer names (each on a new line)
        - "出演：" followed by performer names
        - Multiple performers separated by line breaks, <br>, or other delimiters
        """
        performers = []

        # First, normalize line breaks - convert <br>, <br/>, <br /> to newlines
        normalized_text = re.sub(r"<br\s*/?>", "\n", event_text, flags=re.IGNORECASE)

        # Look for performer sections - use [\s\S] to match across newlines
        performer_patterns = [
            r"\[出演\][:：]?\s*([\s\S]+?)(?:OPEN|開場|前売|¥|￥|\d{1,2}[:：]\d{2})",
            r"出演[:：]\s*([\s\S]+?)(?:OPEN|開場|前売|¥|￥|\d{1,2}[:：]\d{2})",
            r"【出演】[:：]?\s*([\s\S]+?)(?:OPEN|開場|前売|¥|￥|\d{1,2}[:：]\d{2})",
            r"出演者[:：]\s*([\s\S]+?)(?:OPEN|開場|前売|¥|￥|\d{1,2}[:：]\d{2})",
        ]

        for pattern in performer_patterns:
            matches = re.findall(pattern, normalized_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            for match in matches:
                # Split by line breaks first (primary delimiter for Marble)
                lines = match.split("\n")
                for raw_line in lines:
                    line = raw_line.strip()
                    if not line:
                        continue

                    # Also split by other common delimiters within a line
                    names = re.split(r"[,、／/・&×]", line)
                    for name in names:
                        cleaned_name = self._clean_performer_name(name.strip())
                        if cleaned_name and self._is_valid_performer_name(cleaned_name):
                            performers.append(cleaned_name)

        # If no performers found with patterns, try to extract from lines
        if not performers:
            lines = event_text.split("\n")
            for line in lines[:10]:  # Check first 10 lines
                cleaned_line = line.strip()
                if self._is_likely_marble_performer(cleaned_line):
                    cleaned_name = self._clean_performer_name(cleaned_line)
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

    def _is_likely_marble_performer(self, text: str) -> bool:
        """Check if text is likely a performer name in Marble context."""
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
            r"^(OPEN|START|CLOSE)$",
            r"^(チケット|ticket|予約|問い合わせ)$",
            r"^(※|注意|info|information).*",
            r"^(drink|1drink|ドリンク)$",
            r"^(前売|当日|advance|door)$",
            r"^新宿.*Marble$",  # Venue name
            r"TEL|FAX|tel|fax",
            r"http",
            r"www\.",
        ]

        for pattern in skip_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        # Must contain meaningful characters
        return bool(re.search(r"[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", text))

    def _extract_marble_event_name(self, event_text: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event name from Marble event text."""
        # Look for event names in quotes or special formatting
        title_patterns = [
            r"『([^』]+)』",  # Japanese quotes
            r"「([^」]+)」",  # Japanese quotes
            r'"([^"]+)"',  # Regular quotes
            r"'([^']+)'",  # Single quotes
            r"【([^】]+)】",  # Special brackets
            r"■([^■\n]+)",  # Bullet point titles
        ]

        for pattern in title_patterns:
            match = re.search(pattern, event_text)
            if match:
                title = match.group(1).strip()
                MIN_TITLE_LENGTH = 2  # noqa: N806
                MAX_TITLE_LENGTH = 100  # noqa: N806
                if MIN_TITLE_LENGTH < len(title) <= MAX_TITLE_LENGTH:
                    return title

        return None

    def _extract_marble_times(self, event_text: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract open and start times from Marble event text."""
        # Default times
        times = {"open_time": "18:30", "start_time": "19:00"}

        # Look for Marble time patterns
        time_patterns = [
            r"OPEN\s*[:：]?\s*(\d{1,2}[:：]\d{2})\s*/?\s*START\s*[:：]?\s*(\d{1,2}[:：]\d{2})",
            r"開場\s*[:：]?\s*(\d{1,2}[:：]\d{2})\s*/?\s*開演\s*[:：]?\s*(\d{1,2}[:：]\d{2})",
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

    def _extract_from_detail_page(self, html_content: str) -> dict | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event details from a detail page."""
        soup = self.create_soup(html_content)

        try:
            # Look for the event description container
            event_div = soup.find("div", class_="mec-single-event-description")
            if not event_div:
                event_div = soup.find("div", class_="mec-events-content")

            # Fallback to searching for <p> tag with event info
            if not event_div:
                for p in soup.find_all("p"):
                    p_text = p.get_text()
                    if "[出演]" in p_text or "出演" in p_text:
                        event_div = p
                        break

            if not event_div:
                return None

            # Extract text with newline separators to preserve <br> tags
            event_text = event_div.get_text(separator="\n")
            lines = event_text.split("\n")

            # Extract date
            date_str = None
            date_pattern = r"(\d{4})/(\d{1,2})/(\d{1,2})"
            for line in lines:
                date_match = re.search(date_pattern, line)
                if date_match:
                    year = int(date_match.group(1))
                    month = int(date_match.group(2))
                    day = int(date_match.group(3))
                    date_str = f"{year:04d}-{month:02d}-{day:02d}"
                    break

            if not date_str:
                return None

            # Extract event name
            event_name = None
            for line in lines:
                if "「" in line and "」" in line:
                    title_match = re.search(r"「([^」]+)」", line)
                    if title_match:
                        event_name = title_match.group(1)
                        break

            # Extract performers - find lines after [出演] and before OPEN
            performers = []
            in_performer_section = False
            for raw_line in lines:
                line = raw_line.strip()

                if "[出演]" in line or "出演" in line:
                    in_performer_section = True
                    continue

                if in_performer_section:
                    # Stop at OPEN or time patterns
                    if "OPEN" in line or "開場" in line or re.search(r"\d{1,2}:\d{2}", line):
                        break

                    # Skip empty lines
                    if not line:  # noqa: E501
                        continue

                    # Clean and validate performer name
                    cleaned_name = self._clean_performer_name(line)
                    if (
                        cleaned_name
                        and self._is_valid_performer_name(cleaned_name)
                        and len(cleaned_name) >= MIN_PERFORMER_NAME_LENGTH
                        and len(cleaned_name) <= MAX_PERFORMER_NAME_LENGTH
                    ):
                        performers.append(cleaned_name)

            if not performers:
                return None

            # Extract times
            times = self._extract_marble_times(event_text)

            schedule: dict = {
                "date": date_str,
                "open_time": times["open_time"],
                "start_time": times["start_time"],
                "performers": performers[:8],  # Limit to 8
                "performance_name": event_name,
            }
            # Look for event flyer image on the detail page
            for img in soup.find_all("img", src=True):
                src = img["src"]
                if any(skip in src.lower() for skip in ["icon", "logo", "arrow", "btn", "button", "nav", "header"]):
                    continue
                schedule["event_image_url"] = urljoin(self.base_url, src)
                break

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting from detail page")
            return None
        else:
            return schedule

    def find_next_month_link(self, html_content: str) -> str | None:
        """Find next month link for Shinjuku Marble website."""
        soup = self.create_soup(html_content)

        # Look for month navigation links
        nav_patterns = ["next", "次", "翌月", "来月", "→", "＞", ">"]

        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            text = link.get_text().lower()

            # Check if this looks like a next month link
            for pattern in nav_patterns:
                if pattern in text or pattern in href.lower():
                    full_url = urljoin(self.base_url, href)
                    return full_url

        return None
