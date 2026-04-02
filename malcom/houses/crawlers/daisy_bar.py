import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)

# Constants
MIN_PERFORMER_NAME_LENGTH = 2  # noqa: N806
MAX_PERFORMER_NAME_LENGTH = 100  # noqa: N806
max_events = 50
MAX_PERFORMERS = 8  # noqa: N806


@CrawlerRegistry.register("DaisyBarCrawler")
class DaisyBarCrawler(LiveHouseWebsiteCrawler):
    """
    Specialized crawler for Daisy Bar website (https://daisybar.jp/).

    Handles the specific structure of Daisy Bar's schedule page including:
    - Event listings with date format (YYYY/MM/DD)
    - Performer extraction from image alt text and event descriptions
    - Time format (OPEN HH:MM / START HH:MM)
    - Ticket information (前売/当日 prices)
    """

    def find_schedule_link(self, html_content: str) -> str | None:
        """Find the schedule link for Daisy Bar website."""
        # Daisy Bar requires year/month in URL: https://daisybar.jp/schedule/{YEAR}/{MONTH}/
        current_date = timezone.localdate()
        year = current_date.year
        month = current_date.month

        # Construct the current month schedule URL
        schedule_url = f"https://daisybar.jp/schedule/{year}/{month:02d}/"
        logger.debug(f"Constructed schedule URL for Daisy Bar: {schedule_url}")
        return schedule_url

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performance schedules from Daisy Bar's website.

        Handles the specific structure:
        - Events in <article class="schedule-ticket">
        - Date format MM/DD in spans with year from URL
        - Performer names in <p class="artist">
        - Event names and times in specific divs
        """
        schedules = []
        soup = self.create_soup(html_content)

        try:
            # Extract year from current URL or use current year
            current_date = timezone.localdate()
            year = current_date.year

            # Find all event articles
            articles = soup.find_all("article", class_="schedule-ticket")
            logger.debug(f"Found {len(articles)} event articles")

            for article in articles:
                try:
                    schedule = self._parse_daisy_article(article, year)
                    if schedule:
                        schedules.append(schedule)
                except Exception:  # noqa: BLE001
                    logger.exception("Error parsing Daisy Bar article")
                    continue

            # Limit to reasonable number of events
            max_events = 50
            schedules = schedules[:max_events]

            logger.info(f"Extracted {len(schedules)} schedules from Daisy Bar website")

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting Daisy Bar schedules")
            return []
        else:
            return schedules

    def _extract_article_date(self, article: "Tag", year: int) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract date from Daisy Bar article."""
        date_div = article.find("div", class_="schedule-list-date")
        if not date_div:
            return None

        month_span = date_div.find("span", class_="month")
        day_span = date_div.find("span", class_="day")

        if not month_span or not day_span:
            return None

        # Extract numbers from text (e.g., "11 /" -> 11, "01" -> 1)
        month_text = month_span.get_text(strip=True).replace("/", "").strip()
        day_text = day_span.get_text(strip=True)

        try:
            month = int(month_text)
            day = int(day_text)
        except ValueError:
            return None

        return f"{year:04d}-{month:02d}-{day:02d}"

    def _clean_performer_text(self, text: str) -> str:
        """Clean performer text by removing brackets and labels."""
        cleaned = re.sub(r"【.*?】", "", text)
        cleaned = re.sub(r"\[.*?\]", "", cleaned)
        cleaned = re.sub(r"\(.*?\)", "", cleaned)
        return cleaned.strip()

    def _extract_article_performers(self, head_div: "Tag") -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performers from article head div."""
        performers = []
        artist_p = head_div.find("p", class_="artist")
        if not artist_p:
            return performers

        artist_text = artist_p.get_text("|", strip=True)
        # Split by various delimiters and clean up
        for delimiter in ["|", "／", "/", "\n", "、"]:
            if delimiter in artist_text:
                parts = artist_text.split(delimiter)
                for raw_part in parts:
                    cleaned_part = self._clean_performer_text(raw_part)
                    if (
                        cleaned_part
                        and len(cleaned_part) >= MIN_PERFORMER_NAME_LENGTH
                        and cleaned_part not in performers
                    ):  # noqa: E501
                        performers.append(cleaned_part)
                return performers

        # No delimiter found, use whole text
        cleaned_text = self._clean_performer_text(artist_text)
        if cleaned_text and len(cleaned_text) >= MIN_PERFORMER_NAME_LENGTH:
            performers.append(cleaned_text)
        return performers

    def _extract_article_times_and_prices(self, mid_div: "Tag") -> tuple[str, str, float | None, float | None]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract times and prices from article mid div."""
        open_time = "18:00"
        start_time = "19:00"
        presale_price = None
        door_price = None

        time_divs = mid_div.find_all("div", recursive=False)
        for div in time_divs:
            p_tags = div.find_all("p")
            if len(p_tags) < 2:  # noqa: PLR2004
                continue

            label = p_tags[0].get_text(strip=True).lower()
            value = p_tags[1].get_text(strip=True)

            if "open" in label:
                open_time = value
            elif "start" in label:
                start_time = value
            elif "前売" in label or "adv" in label:
                price_match = re.search(r"[¥￥]?\s*(\d[,\d]+)", value)
                if price_match:
                    presale_price = float(price_match.group(1).replace(",", ""))
            elif "当日" in label or "door" in label:
                price_match = re.search(r"[¥￥]?\s*(\d[,\d]+)", value)
                if price_match:
                    door_price = float(price_match.group(1).replace(",", ""))

        return open_time, start_time, presale_price, door_price

    def _parse_daisy_article(self, article: "Tag", year: int) -> dict | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse a single Daisy Bar event article."""
        date_str = self._extract_article_date(article, year)
        if not date_str:
            return None

        # Extract event title and performers
        head_div = article.find("div", class_="schedule-list-content_head")
        event_name = None
        performers = []

        if head_div:
            h2 = head_div.find("h2")
            if h2:
                event_name = h2.get_text(" ", strip=True)
            performers = self._extract_article_performers(head_div)

        # Extract times and prices
        open_time = "18:00"
        start_time = "19:00"
        presale_price = None
        door_price = None

        mid_div = article.find("div", class_="schedule-list-content_mid")
        if mid_div:
            open_time, start_time, presale_price, door_price = self._extract_article_times_and_prices(mid_div)

        if not performers:
            return None

        schedule: dict = {
            "date": date_str,
            "open_time": open_time,
            "start_time": start_time,
            "performers": performers[:MAX_PERFORMERS],
            "performance_name": event_name,
            "presale_price": presale_price,
            "door_price": door_price,
        }
        img = article.find("img", src=True)
        if img:
            schedule["event_image_url"] = urljoin(self.base_url, img["src"])
        return schedule

    def _parse_container_events(self, containers: list) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse events from specific containers."""
        schedules = []

        for container in containers:
            # Look for date patterns in the container
            container_text = container.get_text()

            # Daisy Bar date pattern: YYYY/MM/DD format
            date_pattern = r"(\d{4})/(\d{1,2})/(\d{1,2})"
            date_match = re.search(date_pattern, container_text)

            if date_match:
                year = int(date_match.group(1))
                month = int(date_match.group(2))
                day = int(date_match.group(3))

                # Extract performers and event info
                performers = self._extract_daisy_performers(container)
                event_name = self._extract_daisy_event_name(container_text)
                times = self._extract_daisy_times(container_text)

                if performers:
                    schedule_data = {
                        "date": f"{year:04d}-{month:02d}-{day:02d}",
                        "open_time": times["open_time"],
                        "start_time": times["start_time"],
                        "performers": performers,
                        "performance_name": event_name,
                    }
                    schedules.append(schedule_data)

                    logger.debug(f"Extracted Daisy Bar event: {schedule_data['date']} - {performers}")

        return schedules

    def _parse_text_events(self, soup: "Tag") -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse events from text content."""
        schedules = []
        text = soup.get_text()

        # Daisy Bar date pattern: YYYY/MM/DD format
        date_pattern = r"(\d{4})/(\d{1,2})/(\d{1,2})"
        date_matches = list(re.finditer(date_pattern, text))

        for match in date_matches[:30]:  # Limit to 30 events
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))

            # Extract event content around this date
            start_pos = match.end()

            # Find the next date or take next 1000 chars
            next_date_match = re.search(date_pattern, text[start_pos:])
            if next_date_match:
                end_pos = start_pos + next_date_match.start()
                event_content = text[start_pos:end_pos]
            else:
                event_content = text[start_pos : start_pos + 1000]

            # Also check content before the date
            pre_start = max(0, match.start() - 500)
            pre_content = text[pre_start : match.start()]
            full_content = pre_content + " " + event_content

            # Extract performers and event info
            performers = self._extract_daisy_performers_text(full_content)
            event_name = self._extract_daisy_event_name(full_content)
            times = self._extract_daisy_times(full_content)

            if performers:
                schedule_data = {
                    "date": f"{year:04d}-{month:02d}-{day:02d}",
                    "open_time": times["open_time"],
                    "start_time": times["start_time"],
                    "performers": performers,
                    "performance_name": event_name,
                }
                schedules.append(schedule_data)

                logger.debug(f"Extracted Daisy Bar event: {schedule_data['date']} - {performers}")

        return schedules

    def _is_valid_performer_name(self, name: str) -> bool:
        """Check if a name is valid for a performer."""
        return MIN_PERFORMER_NAME_LENGTH <= len(name) <= MAX_PERFORMER_NAME_LENGTH

    def _extract_daisy_performers(self, container: "Tag") -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performer names from Daisy Bar event container.
        Looks for image alt text, performer lists, and text content.
        """
        performers = []

        # Method 1: Extract from image alt text (common on Daisy Bar)
        images = container.find_all("img", alt=True)
        for img in images:
            alt_text = img.get("alt", "").strip()
            if self._is_likely_daisy_performer(alt_text):
                cleaned_name = self._clean_performer_text(alt_text)
                if cleaned_name and self._is_valid_performer_name(cleaned_name):
                    performers.append(cleaned_name)

        # Method 2: Look for performer list patterns
        text_content = container.get_text()
        text_performers = self._extract_daisy_performers_text(text_content)

        # Combine and deduplicate
        all_performers = performers + text_performers
        seen = set()
        unique_performers = []
        for performer in all_performers:
            if performer.lower() not in seen:
                seen.add(performer.lower())
                unique_performers.append(performer)

        return unique_performers[:MAX_PERFORMERS]

    def _extract_daisy_performers_text(self, text_content: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performer names from text content."""
        performers = []

        # Look for performer sections with various patterns
        performer_patterns = [
            r"(?:出演|LIVE|ライブ|Artist|アーティスト)[:：\s]*([^\n\r]+)",
            r"【([^】]+)】",  # Content in 【】 brackets
            r"■([^■\n]+)",  # Bullet point content
        ]

        for pattern in performer_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            for match in matches:
                # Split by common delimiters
                names = re.split(r"[,、／/・&×\n\r]", match)
                for raw_name in names:
                    cleaned_name = raw_name.strip()
                    if self._is_likely_daisy_performer(cleaned_name):
                        cleaned_name = self._clean_performer_text(cleaned_name)
                        if cleaned_name and self._is_valid_performer_name(cleaned_name):
                            performers.append(cleaned_name)

        # If no patterns found, look for known performers in lines
        if not performers:
            lines = text_content.split("\n")
            for raw_line in lines[:15]:  # Check first 15 lines
                cleaned_line = raw_line.strip()
                if self._is_likely_daisy_performer(cleaned_line):
                    cleaned_name = self._clean_performer_text(cleaned_line)
                    if cleaned_name and self._is_valid_performer_name(cleaned_name):
                        performers.append(cleaned_name)

        return performers

    def _is_likely_daisy_performer(self, text: str) -> bool:
        """Check if text is likely a performer name in Daisy Bar context."""
        min_text_length = 2
        max_text_length = 100

        if not text or len(text.strip()) < min_text_length or len(text) > max_text_length:
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
            r"^(配信|streaming|live)$",
            r"^(From The Beginning|イベント|Event)$",  # Common event names
            r"TEL|FAX|tel|fax",
            r"http|www\.",
            r"^\d{4}/\d{1,2}/\d{1,2}$",  # Date only
        ]

        for pattern in skip_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        # Must contain meaningful characters
        return bool(re.search(r"[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", text))

    def _extract_daisy_event_name(self, event_text: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event name from Daisy Bar event text."""
        # Look for event names in quotes or special formatting
        title_patterns = [
            r"『([^』]+)』",  # Japanese quotes
            r"「([^」]+)」",  # Japanese quotes
            r'"([^"]+)"',  # Regular quotes
            r"'([^']+)'",  # Single quotes
            r"【([^】]+)】",  # Special brackets (but exclude performer lists)
            r"■([^■\n]+)",  # Bullet point titles
            r"From The Beginning",  # Known event name
        ]

        for pattern in title_patterns:
            matches = re.findall(pattern, event_text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    title = match[0].strip()
                else:
                    title = match.strip()

                min_title_length = 3
                max_title_length = 100

                # Skip if it looks like a performer name
                if not self._is_likely_daisy_performer(title):
                    continue

                if min_title_length < len(title) <= max_title_length:  # noqa: SIM102
                    # Skip common performer indicators
                    if not re.search(r"(出演|LIVE|ライブ|Artist)", title):
                        return title

        return None

    def _extract_daisy_times(self, event_text: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract open and start times from Daisy Bar event text."""
        # Default times
        times = {"open_time": "18:30", "start_time": "19:00"}

        # Look for Daisy Bar time patterns
        time_patterns = [
            r"OPEN\s*[:：]?\s*(\d{1,2}[:：]\d{2})\s*[/\s]*START\s*[:：]?\s*(\d{1,2}[:：]\d{2})",
            r"開場\s*[:：]?\s*(\d{1,2}[:：]\d{2})\s*[/\s]*開演\s*[:：]?\s*(\d{1,2}[:：]\d{2})",
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
        """Find next month link for Daisy Bar website."""
        # Calculate next month with year-aware logic
        current_date = timezone.localdate()
        next_month = (current_date.month % 12) + 1
        next_year = current_date.year if next_month > current_date.month else current_date.year + 1

        # Daisy Bar uses direct URL format: https://daisybar.jp/schedule/{YEAR}/{MONTH}/
        next_month_url = f"https://daisybar.jp/schedule/{next_year}/{next_month:02d}/"
        logger.debug(f"Constructed next month URL for Daisy Bar: {next_month_url}")
        return next_month_url
