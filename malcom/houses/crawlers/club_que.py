import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

if TYPE_CHECKING:
    from bs4 import Tag

logger = logging.getLogger(__name__)


@CrawlerRegistry.register("ClubQueCrawler")
class ClubQueCrawler(LiveHouseWebsiteCrawler):
    """
    Specialized crawler for Club Que website (https://clubque.net/).

    Handles the specific structure of Club Que's schedule page including:
    - Event listings with date format (YYYY/MM/DD)
    - Detail pages with times (OPEN／START format)
    - Ticket pricing (ADV／DOOR format)
    - Performer extraction from event content
    """

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performance schedules from Club Que's website.

        Handles the specific structure:
        - Event detail page links in format /schedule/[ID]/
        - Extract full details from each detail page
        """
        schedules = []

        try:
            # Use the provided HTML content directly (it's already the schedule page)
            soup = self.create_soup(html_content)

            # Find all event detail links
            detail_links = []
            for link in soup.find_all("a", href=True):
                href = link.get("href")
                # Match /schedule/[digits]/ anywhere in the URL
                if href and re.search(r"/schedule/\d+/$", href):
                    full_url = urljoin(self.base_url, href)
                    if full_url not in detail_links:
                        detail_links.append(full_url)

            logger.info(f"Found {len(detail_links)} detail page links")

            # Fetch each detail page and extract event information
            for detail_url in detail_links[:50]:  # Limit to 50 events
                try:
                    detail_html = self.fetch_page(detail_url)
                    if detail_html:
                        schedule = self._extract_from_detail_page(detail_html)
                        if schedule:
                            schedules.append(schedule)
                            performance_name = schedule.get("performance_name", "N/A")
                            logger.debug(f"✓ Extracted event: {schedule['date']} - {performance_name}")
                        else:
                            logger.warning(f"✗ Failed to extract schedule from detail page: {detail_url}")
                except Exception:  # noqa: BLE001
                    logger.exception(f"Failed to fetch detail page: {detail_url}")
                    continue

            logger.info(f"Extracted {len(schedules)} schedules from Club Que website")

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting Club Que schedules")
            return []
        else:
            return schedules

    def _extract_date(self, soup: "Tag") -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract and parse date from Club Que detail page."""
        date_elem = soup.find("span", class_="date")
        if not date_elem:
            logger.debug("No date element found")
            return None

        date_text = date_elem.get_text(strip=True)
        # Parse date like "2025/10/01 (Wed)" or "2025/10/01"
        date_match = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", date_text)
        if not date_match:
            logger.debug(f"Could not parse date from: {date_text}")
            return None

        year = int(date_match.group(1))
        month = int(date_match.group(2))
        day = int(date_match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _extract_times(self, soup: "Tag") -> tuple[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract open and start times from Club Que detail page."""
        open_time = "18:00"
        start_time = "19:00"
        time_elem = soup.find("dl", class_="schedule-content__openstart")
        if time_elem:
            time_dd = time_elem.find("dd")
            if time_dd:
                time_text = time_dd.get_text(strip=True)
                # Parse "18:30／19:00" or "18:30/19:00"
                time_match = re.search(r"(\d{1,2}:\d{2})[／/]\s*(\d{1,2}:\d{2})", time_text)
                if time_match:
                    open_time = time_match.group(1)
                    start_time = time_match.group(2)
        return open_time, start_time

    def _extract_event_name(self, soup: "Tag") -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event name from Club Que detail page."""
        title_elem = soup.find("p", class_="title-after2")
        if title_elem:
            return title_elem.get_text(strip=True)

        h1_elem = soup.find("h1")
        if h1_elem:
            return h1_elem.get_text(strip=True)
        return None

    def _extract_pricing(self, soup: "Tag") -> tuple[float | None, float | None]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract presale and door pricing from Club Que detail page."""
        presale_price = None
        door_price = None
        ticket_elem = soup.find("dl", class_="schedule-content__ticket")
        if ticket_elem:
            ticket_dd = ticket_elem.find("dd")
            if ticket_dd:
                price_text = ticket_dd.get_text()
                # Parse "ADV.￥5,500／DOOR.￥6,000" or "ADV 5000/DOOR 5500"
                adv_match = re.search(r"ADV[.\s:：]*[￥¥]?\s*(\d[,\d]+)", price_text, re.IGNORECASE)
                door_match = re.search(r"DOOR[.\s:：]*[￥¥]?\s*(\d[,\d]+)", price_text, re.IGNORECASE)
                if adv_match:
                    presale_price = float(adv_match.group(1).replace(",", ""))
                if door_match:
                    door_price = float(door_match.group(1).replace(",", ""))
        return presale_price, door_price

    def _extract_from_detail_page(self, html_content: str) -> dict | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event details from a Club Que detail page."""
        soup = self.create_soup(html_content)

        try:
            date_str = self._extract_date(soup)
            if not date_str:
                return None

            open_time, start_time = self._extract_times(soup)
            event_name = self._extract_event_name(soup)
            performers = self._extract_performers(soup)
            presale_price, door_price = self._extract_pricing(soup)

            if not performers:
                logger.debug(f"No performers found for {date_str}")
                return None

            return {
                "date": date_str,
                "open_time": open_time,
                "start_time": start_time,
                "performers": performers[:8],  # Limit to 8 performers
                "performance_name": event_name,
                "presale_price": presale_price,
                "door_price": door_price,
            }

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting from Club Que detail page")
            return None

    def _should_skip_line(self, line_text: str) -> bool:
        """Check if a line should be skipped during performer extraction."""
        if not line_text or len(line_text) < 2 or len(line_text) > 100:  # noqa: PLR2004
            return True

        # Skip date, title, tags, and other metadata
        skip_terms = [
            "schedule",
            "streaming",
            "配信あり",
            "sold out",
            "2025/",
            "(mon)",
            "(tue)",
            "(wed)",
            "(thu)",
            "(fri)",
            "(sat)",
            "(sun)",
        ]
        return any(skip in line_text.lower() for skip in skip_terms)

    def _clean_performer_name(self, name: str) -> str:
        """Clean performer name by removing unwanted content."""
        # Remove bracketed content like [members]
        cleaned = re.sub(r"\[.*?\]", "", name).strip()
        # Remove parenthetical content
        cleaned = re.sub(r"\(.*?\)", "", cleaned).strip()
        # Remove trailing punctuation
        return cleaned.rstrip("｜|,")

    def _is_valid_performer_name(self, name: str) -> bool:
        """Check if a name looks like a valid performer name."""
        if not name or len(name) < 2 or len(name) > 100:  # noqa: PLR2004
            return False

        skip_terms = ["guest", "special", "dj＞", "open", "start", "ticket", "adv", "door"]
        return not any(skip in name.lower() for skip in skip_terms)

    def _extract_bullet_performer(self, line_text: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performer from bullet-point line."""
        if not line_text.startswith("・"):
            return None

        performer_name = self._clean_performer_name(line_text.lstrip("・"))
        if performer_name and len(performer_name) >= 2:  # noqa: PLR2004
            return performer_name
        return None

    def _extract_separator_performers(self, line_text: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performers from line with separator."""
        if "｜" not in line_text and "|" not in line_text:
            return []

        performers = []
        parts = re.split(r"[｜|]", line_text)
        for raw_part in parts:
            cleaned_part = re.sub(r"[\[【\(].*?[\]】\)]", "", raw_part.strip()).strip()
            if self._is_valid_performer_name(cleaned_part):
                performers.append(cleaned_part)
        return performers

    def _remove_duplicates(self, performers: list[str]) -> list[str]:
        """Remove duplicate performers while preserving order."""
        seen = set()
        unique_performers = []
        for performer in performers:
            performer_lower = performer.lower()
            if performer_lower not in seen:
                seen.add(performer_lower)
                unique_performers.append(performer)
        return unique_performers

    def _extract_performers(self, soup: "Tag") -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performer names from Club Que event page."""
        # Look for header content area
        header = soup.find("header", class_="schedule-content__header")
        if not header:
            return []

        text_content = header.get_text(separator="\n")
        lines = text_content.split("\n")

        performers = []
        for raw_line in lines:
            line_text = raw_line.strip()
            if self._should_skip_line(line_text):
                continue

            # Try bullet-point performer
            bullet_performer = self._extract_bullet_performer(line_text)
            if bullet_performer:
                performers.append(bullet_performer)
                continue

            # Try separator performers
            separator_performers = self._extract_separator_performers(line_text)
            performers.extend(separator_performers)

        return self._remove_duplicates(performers)

    def find_next_month_link(self, html_content: str) -> str | None:
        """Find next month link for Club Que website."""
        soup = self.create_soup(html_content)

        # Look for "次の月" (next month) link
        for link in soup.find_all("a", href=True):
            if "次の月" in link.get_text():
                href = link.get("href")
                if href:
                    return urljoin(self.base_url, href)

        return None
