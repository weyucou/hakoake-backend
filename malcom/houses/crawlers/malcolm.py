import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)


@CrawlerRegistry.register("MalcolmCrawler")
class MalcolmCrawler(LiveHouseWebsiteCrawler):
    """
    Specialized crawler for Club Malcolm website (https://club-malcolm.com/).

    Handles the specific structure of Malcolm's schedule page including:
    - Event listings with -LIVE- and -DJ- sections
    - Date format (M/D(DAY))
    - Performer extraction from LIVE sections
    - Event names and ticket information
    """

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performance schedules from Malcolm's website.

        Handles the specific structure:
        - Events with date format like "7/5(SAT)"
        - -LIVE- sections for performers
        - -DJ- sections (which we'll include as performers)
        - Event names and descriptions
        """
        schedules = []
        soup = self.create_soup(html_content)

        try:
            # Look for event containers or date patterns
            text = soup.get_text()

            # Malcolm date pattern: M/D(DAY) format
            date_pattern = r"(\d{1,2})/(\d{1,2})\s*\([^)]+\)"
            date_matches = list(re.finditer(date_pattern, text))

            current_year = datetime.now().year  # noqa: DTZ001
            current_month = datetime.now().month  # noqa: DTZ001

            for i, match in enumerate(date_matches):
                month = int(match.group(1))
                day = int(match.group(2))

                # Determine year
                year = current_year
                if month < current_month:
                    year += 1

                # Extract event content after this date
                start_pos = match.end()

                # Find the next date or end of content
                if i + 1 < len(date_matches):  # noqa: PLR2004
                    end_pos = date_matches[i + 1].start()
                    event_content = text[start_pos:end_pos]
                else:
                    event_content = text[start_pos : start_pos + 1000]  # Take next 1000 chars

                # Extract performers and event info from this section
                performers = self._extract_malcolm_performers(event_content)
                event_name = self._extract_malcolm_event_name(event_content)
                times = self._extract_malcolm_times(event_content)

                if performers:
                    schedule_data = {
                        "date": f"{year}-{month:02d}-{day:02d}",
                        "open_time": times["open_time"],
                        "start_time": times["start_time"],
                        "performers": performers,
                        "performance_name": event_name,
                    }
                    schedules.append(schedule_data)

                    logger.debug(f"Extracted Malcolm event: {schedule_data['date']} - {performers}")

                # Limit to reasonable number of events
                MAX_EVENTS = 30  # noqa: N806
                if len(schedules) >= MAX_EVENTS:
                    break

            logger.info(f"Extracted {len(schedules)} schedules from Malcolm website")

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting Malcolm schedules")
            return []
        else:
            return schedules

    def _extract_malcolm_performers(self, event_text: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performer names from Malcolm event text.

        Handles patterns like:
        - "-LIVE-" sections with performer names
        - "-DJ-" sections with DJ names
        - Multiple performers listed line by line
        """
        performers = []

        # Look for -LIVE- and -DJ- sections
        live_sections = re.findall(r"-LIVE-\s*(.*?)(?=-DJ-|$)", event_text, re.DOTALL | re.IGNORECASE)
        dj_sections = re.findall(r"-DJ-\s*(.*?)(?=-LIVE-|$)", event_text, re.DOTALL | re.IGNORECASE)

        # Process LIVE sections
        for section in live_sections:
            section_performers = self._parse_malcolm_performer_section(section)
            performers.extend(section_performers)

        # Process DJ sections (DJs are also performers)
        for section in dj_sections:
            section_performers = self._parse_malcolm_performer_section(section)
            performers.extend(section_performers)

        # If no sections found, try to extract from the whole text
        if not performers:
            # Look for performer-like lines
            lines = event_text.split("\n")
            for line in lines:
                cleaned_line = line.strip()
                if cleaned_line and self._is_likely_malcolm_performer(cleaned_line):
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

    def _parse_malcolm_performer_section(self, section_text: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse a LIVE or DJ section to extract performer names."""
        performers = []

        # Clean the section
        text = section_text.strip()

        # Remove common Malcolm non-performer text
        malcolm_noise = [
            r"OPEN\s+\d{1,2}:\d{2}",
            r"START\s+\d{1,2}:\d{2}",
            r"[¥￥]\s*\d+[,\d]*",
            r"1DRINK\s*[¥￥]\s*\d+",
            r"チケット.*",
            r"予約.*",
            r"問い合わせ.*",
            r"※.*",
        ]

        for pattern in malcolm_noise:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Split by lines and common delimiters
        lines = text.split("\n")
        for line in lines:
            cleaned_line = line.strip()

            # Skip empty lines or obvious non-performer content
            MIN_LINE_LENGTH = 2  # noqa: N806
            if not cleaned_line or len(cleaned_line) < MIN_LINE_LENGTH:
                continue

            # Further split by common delimiters within a line
            potential_performer_names = re.split(r"[/／、・&×]", cleaned_line)

            for performer_name in potential_performer_names:
                cleaned_performer = performer_name.strip()

                if self._is_likely_malcolm_performer(cleaned_performer):
                    cleaned_name = self._clean_performer_name(cleaned_performer)
                    MAX_PERFORMER_NAME_LENGTH = 100  # noqa: N806
                    if (
                        cleaned_name
                        and self._is_valid_performer_name(cleaned_name)
                        and len(cleaned_name) <= MAX_PERFORMER_NAME_LENGTH
                    ):
                        performers.append(cleaned_name)

        return performers

    def _is_likely_malcolm_performer(self, text: str) -> bool:
        """Check if text is likely a performer name in Malcolm context."""
        MIN_TEXT_LENGTH = 2  # noqa: N806
        if not text or len(text.strip()) < MIN_TEXT_LENGTH:
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
            r"^(drink|1drink|食事|food)$",
            r"^(advance|当日|前売|door)$",
            r"^(問い合わせ|contact|tel|phone).*",
            r"対応できかねます",
            r"締めきりました",
            r"受付.*",
            r"合宿.*",
            r"初日.*",
            # Date patterns (e.g., "11/15(SAT", "11/16(SUN")
            r"^\d{1,2}/\d{1,2}\s*\(",  # MM/DD( format
            r"^\d{1,2}/\d{1,2}\s*$",  # MM/DD only
        ]

        for pattern in skip_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        # Must contain meaningful characters
        return bool(re.search(r"[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", text))

    def _extract_malcolm_event_name(self, event_text: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event name from Malcolm event text."""
        # Look for event names in quotes or special formatting
        title_patterns = [
            r"『([^』]+)』",  # Japanese quotes
            r"「([^」]+)」",  # Japanese quotes
            r'"([^"]+)"',  # Regular quotes
            r"'([^']+)'",  # Single quotes
            r"【([^】]+)】",  # Special brackets
        ]

        for pattern in title_patterns:
            match = re.search(pattern, event_text)
            if match:
                title = match.group(1).strip()
                MIN_TITLE_LENGTH = 2  # noqa: N806
                MAX_TITLE_LENGTH = 100  # noqa: N806
                if MIN_TITLE_LENGTH < len(title) <= MAX_TITLE_LENGTH:
                    return title

        # Look for lines that look like event titles (usually early in the text)
        lines = event_text.split("\n")[:5]  # Check first 5 lines
        for line in lines:
            cleaned_line = line.strip()
            MIN_TITLE_LENGTH = 3  # noqa: N806
            MAX_TITLE_LENGTH = 100  # noqa: N806
            if (
                cleaned_line
                and MIN_TITLE_LENGTH < len(cleaned_line) <= MAX_TITLE_LENGTH
                and not re.search(r"\d{1,2}:\d{2}", cleaned_line)  # No times
                and not re.search(r"[¥￥]\d+", cleaned_line)  # No prices
                and not any(
                    marker in cleaned_line.lower() for marker in ["live", "dj", "presents"]
                )  # Skip if it looks like performer names
            ):
                return cleaned_line

        return None

    def _extract_malcolm_times(self, event_text: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract open and start times from Malcolm event text."""
        # Default times
        times = {"open_time": "18:30", "start_time": "19:00"}

        # Look for Malcolm time patterns
        time_patterns = [
            r"OPEN\s+(\d{1,2}:\d{2})\s*/?\s*START\s+(\d{1,2}:\d{2})",
            r"開場\s+(\d{1,2}:\d{2})\s*/?\s*開演\s+(\d{1,2}:\d{2})",
            r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
        ]

        for pattern in time_patterns:
            match = re.search(pattern, event_text, re.IGNORECASE)
            if match:
                times["open_time"] = match.group(1)
                times["start_time"] = match.group(2)
                break

        return times

    def find_next_month_link(self, html_content: str) -> str | None:
        """Find next month link for Malcolm website."""
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
