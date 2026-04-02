import logging
import re
from urllib.parse import urljoin

from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)


@CrawlerRegistry.register("LaMamaCrawler")
class LaMamaCrawler(LiveHouseWebsiteCrawler):
    """Crawler for La Mama website."""

    def extract_live_house_info(self, html_content: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract live house information from the La Mama page."""
        soup = self.create_soup(html_content)

        # Initialize with empty values
        info = {
            "name": "",
            "name_kana": "",
            "name_romaji": "",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

        # Extract name from title or header
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text()
            if "La.mama" in title_text or "ラママ" in title_text:
                info["name"] = "Shibuya La.mama"
                info["name_kana"] = "シブヤ ラママ"
                info["name_romaji"] = "Shibuya La.mama"

        # Look for about/info section
        info_sections = soup.find_all(["div", "section"], class_=re.compile(r"about|info|venue", re.IGNORECASE))

        for section in info_sections:
            section_text = section.get_text()

            # Extract address
            address_patterns = [
                r"(東京都.*?[0-9-]+)",
                r"(渋谷区.*?[0-9-]+)",
            ]
            for pattern in address_patterns:
                address_match = re.search(pattern, section_text)
                if address_match:
                    info["address"] = address_match.group(1).strip()
                    break

            # Extract phone number
            phone_match = re.search(r"(\d{2,4}-\d{2,4}-\d{4})", section_text)
            if phone_match:
                info["phone_number"] = phone_match.group(1)

            # Extract capacity
            capacity_match = re.search(r"(\d{2,4})\s*人|(\d{2,4})\s*名", section_text)
            if capacity_match:
                info["capacity"] = int(capacity_match.group(1) or capacity_match.group(2))

        # Alternative search in footer or contact areas
        footer = soup.find(["footer", "div"], id=re.compile(r"footer|contact", re.IGNORECASE))
        if footer and not info["phone_number"]:
            footer_text = footer.get_text()
            phone_match = re.search(r"(\d{2,4}-\d{2,4}-\d{4})", footer_text)
            if phone_match:
                info["phone_number"] = phone_match.group(1)

        # Look for establishment information
        history_patterns = ["since", "創業", "開店", "オープン", "設立"]
        for pattern in history_patterns:
            history_elem = soup.find(text=re.compile(pattern, re.IGNORECASE))
            if history_elem:
                parent_text = history_elem.parent.get_text() if history_elem.parent else str(history_elem)
                year_match = re.search(r"(\d{4})", parent_text)
                if year_match:
                    year = int(year_match.group(1))
                    info["opened_date"] = f"{year}-01-01"
                    break

        return info

    def find_schedule_link(self, html_content: str) -> str | None:
        """Find the link to the schedule page on La Mama site."""
        # La.mama requires year-month in URL: https://www.lamama.net/schedule/?month={YEAR}-{MONTH}
        current_date = timezone.localdate()
        year = current_date.year
        month = current_date.month

        # Construct the current month schedule URL
        schedule_url = f"https://www.lamama.net/schedule/?month={year}-{month:02d}"
        logger.debug(f"Constructed schedule URL for La.mama: {schedule_url}")
        return schedule_url

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performance schedules from La Mama schedule page."""
        soup = self.create_soup(html_content)
        schedules = []

        # La.mama uses <a class="pickup_btn schedule"> for each event
        event_links = soup.find_all("a", class_="pickup_btn schedule")
        logger.debug(f"Found {len(event_links)} event links")

        for event_link in event_links:
            try:
                schedule = self._parse_lamama_event(event_link)
                if schedule:
                    schedules.append(schedule)
            except Exception:  # noqa: BLE001
                logger.exception("Error parsing La.mama event")
                continue

        logger.info(f"Extracted {len(schedules)} schedules from La.mama website")
        return schedules

    def _parse_lamama_event(self, event_link: str) -> dict | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Parse a single La.mama event link."""
        # Extract date from data-schedule attribute (format: "2025-11-01")
        date_str = event_link.get("data-schedule")
        if not date_str:
            return None

        # Extract event name from <p class="event">
        event_name = None
        event_p = event_link.find("p", class_="event")
        if event_p:
            event_name = event_p.get_text(strip=True)

        # Extract performers from <p class="member">
        performers = []
        member_p = event_link.find("p", class_="member")
        if member_p:
            member_text = member_p.get_text(strip=True)
            # Split by "/" and clean up
            parts = re.split(r"\s*/\s*", member_text)
            for raw_part in parts:
                part = raw_part.strip()
                # Remove bracketed content and labels like 【生誕】
                part = re.sub(r"【.*?】", "", part)
                part = re.sub(r"\[.*?\]", "", part)
                part = re.sub(r"\(.*?\)", "", part)
                part = re.sub(r"（.*?）", "", part)
                # Remove "with" and similar connectors
                part = re.sub(r"\s+with\s+.*", "", part, flags=re.IGNORECASE)
                part = part.strip()

                if part and len(part) >= 2 and part not in performers:  # noqa: PLR2004
                    performers.append(part)

        # Default times (La.mama doesn't seem to show times in the list view)
        open_time = "18:30"
        start_time = "19:00"

        if not performers:
            return None

        schedule: dict = {
            "date": date_str,
            "open_time": open_time,
            "start_time": start_time,
            "performers": performers[:8],
            "performance_name": event_name,
        }
        img = event_link.find("img", src=True)
        if img:
            schedule["event_image_url"] = urljoin("https://www.lamama.net", img["src"])
        return schedule

    def find_next_month_link(self, html_content: str) -> str | None:
        """Find the link to next month's schedule page."""
        # Calculate next month with year-aware logic
        current_date = timezone.localdate()
        next_month = (current_date.month % 12) + 1
        next_year = current_date.year if next_month > current_date.month else current_date.year + 1

        # La.mama uses direct URL format: https://www.lamama.net/schedule/?month={YEAR}-{MONTH}
        next_month_url = f"https://www.lamama.net/schedule/?month={next_year}-{next_month:02d}"
        logger.debug(f"Constructed next month URL for La.mama: {next_month_url}")
        return next_month_url
