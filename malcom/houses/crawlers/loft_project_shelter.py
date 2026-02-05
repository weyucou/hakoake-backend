import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)


@CrawlerRegistry.register("LoftProjectShelterCrawler")
class LoftProjectShelterCrawler(LiveHouseWebsiteCrawler):
    """Crawler for Loft Project Shelter website."""

    def extract_live_house_info(self, html_content: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract live house information from the Loft Project Shelter page."""
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

        self._extract_venue_name(soup, info)
        self._extract_address(soup, info)
        self._extract_contact_info(soup, info)
        self._extract_capacity(soup, info)
        self._extract_establishment_date(soup, info)

        return info

    def _extract_venue_name(self, soup: BeautifulSoup, info: dict) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract venue name from page title."""
        title_tag = soup.find("title")
        if title_tag and "SHELTER" in title_tag.get_text():
            info["name"] = "Shimokitazawa SHELTER"
            info["name_kana"] = "シモキタザワ シェルター"
            info["name_romaji"] = "Shimokitazawa SHELTER"

    def _extract_address(self, soup: BeautifulSoup, info: dict) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract address information."""
        venue_info = soup.find_all(text=re.compile(r"住所|所在地|address", re.IGNORECASE))
        for text in venue_info:
            parent = text.parent
            if parent:
                address_match = re.search(r"(東京都.*?[0-9-]+)", parent.get_text())
                if address_match:
                    info["address"] = address_match.group(1).strip()
                    break

    def _extract_contact_info(self, soup: BeautifulSoup, info: dict) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract contact information."""
        contact_section = soup.find_all(text=re.compile(r"TEL|電話|tel", re.IGNORECASE))
        for text in contact_section:
            parent = text.parent
            if parent:
                phone_match = re.search(r"(\d{2,4}-\d{2,4}-\d{4})", parent.get_text())
                if phone_match:
                    info["phone_number"] = phone_match.group(1)
                    break

    def _extract_capacity(self, soup: BeautifulSoup, info: dict) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract capacity information."""
        capacity_section = soup.find_all(text=re.compile(r"収容|キャパ|capacity", re.IGNORECASE))
        for text in capacity_section:
            parent = text.parent
            if parent:
                capacity_match = re.search(r"(\d{2,4})人?", parent.get_text())
                if capacity_match:
                    info["capacity"] = int(capacity_match.group(1))
                    break

    def _extract_establishment_date(self, soup: BeautifulSoup, info: dict) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract establishment date."""
        history_section = soup.find_all(text=re.compile(r"開店|開業|設立|オープン", re.IGNORECASE))
        for text in history_section:
            parent = text.parent
            if parent:
                date_match = re.search(r"(\d{4})年(\d{1,2})月", parent.get_text())
                if date_match:
                    year = int(date_match.group(1))
                    month = int(date_match.group(2))
                    info["opened_date"] = f"{year}-{month:02d}-01"
                    break

    def find_schedule_link(self, html_content: str) -> str | None:
        """Find the link to the schedule page on Loft Project site."""
        soup = self.create_soup(html_content)

        # The URL already points to the schedule page
        if "/schedule/" in self.website.url:
            return self.website.url

        # Look for schedule link
        schedule_links = soup.find_all("a", href=re.compile(r"/schedule/"))
        for link in schedule_links:
            href = link.get("href")
            if href:
                return urljoin(self.website.url, href)

        # Alternative text-based search
        schedule_text_links = soup.find_all("a", text=re.compile(r"スケジュール|schedule|ライブ", re.IGNORECASE))
        for link in schedule_text_links:
            href = link.get("href")
            if href:
                return urljoin(self.website.url, href)

        return self.website.url  # Assume current page has schedule

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performance schedules from Loft Project Shelter schedule page."""
        soup = self.create_soup(html_content)
        schedules = []

        # Find event links - each event is wrapped in an <a> tag with schedule URL
        event_links = soup.find_all("a", href=re.compile(r"/schedule/shelter/\d+"))

        for link in event_links:
            schedule = self._parse_event_link(link)
            if schedule:
                schedules.append(schedule)

        # Fallback to container-based parsing if no event links found
        if not schedules:
            schedule_containers = soup.find_all(
                ["div", "article", "section"], class_=re.compile(r"schedule|event|live|gig", re.IGNORECASE)
            )
            if not schedule_containers:
                schedule_containers = [soup]

            for container in schedule_containers:
                container_schedules = self._process_schedule_container(container)
                schedules.extend(container_schedules)

        return schedules

    def _parse_event_link(self, link: Tag) -> dict | None:
        """Parse a single event link element to extract schedule data."""
        divs = link.find_all("div", recursive=False)
        if len(divs) < 4:  # noqa: PLR2004
            # Try nested structure
            divs = link.find_all("div")

        # Extract date components (YYYY, MM, DD pattern)
        year, month, day = None, None, None
        for div in divs:
            text = div.get_text(strip=True)
            if re.match(r"^\d{4}$", text):
                year = int(text)
            elif re.match(r"^\d{1,2}$", text) and year and not month:
                month = int(text)
            elif re.match(r"^\d{1,2}$", text) and month and not day:
                day = int(text)

        if not all([year, month, day]):
            return None

        # Extract times from OPEN/START pattern
        open_time = "18:00"
        start_time = "18:30"
        link_text = link.get_text()
        time_match = re.search(r"OPEN\s*(\d{1,2}:\d{2})\s*[-–]\s*START\s*(\d{1,2}:\d{2})", link_text, re.IGNORECASE)
        if time_match:
            open_time = time_match.group(1)
            start_time = time_match.group(2)

        # Extract performers from <ul><li> structure
        performers = []
        ul_elements = link.find_all("ul")
        for ul in ul_elements:
            for li in ul.find_all("li"):
                performer_name = li.get_text(strip=True)
                if performer_name and self._is_valid_performer_name(performer_name):
                    cleaned = self._clean_performer_name(performer_name)
                    if cleaned and len(cleaned) <= 100:  # noqa: PLR2004
                        performers.append(cleaned)

        if not performers:
            return None

        return {
            "date": f"{year}-{month:02d}-{day:02d}",
            "open_time": open_time,
            "start_time": start_time,
            "performers": performers[:10],
        }

    def _process_schedule_container(self, container: BeautifulSoup) -> list[dict]:  # noqa: PLR0912
        """Process a single schedule container to extract events."""
        schedules = []
        current_year = datetime.now().year  # noqa: DTZ001
        current_month = datetime.now().month  # noqa: DTZ001

        # Date patterns for parsing
        date_patterns = [
            r"(\d{4})\s*(\d{2})\s*(\d{2})",  # YYYY MM DD
            r"(\d{1,2})/(\d{1,2})",  # MM/DD fallback
            r"(\d{1,2})月(\d{1,2})日",  # M月D日 (Japanese)
        ]

        container_text = container.get_text()

        # Find all date matches in this container
        for pattern in date_patterns:
            matches = re.finditer(pattern, container_text)
            for match in matches:
                # Parse date from match
                EXPECTED_FULL_DATE_GROUPS = 3  # noqa: N806
                EXPECTED_PARTIAL_DATE_GROUPS = 2  # noqa: N806
                if len(match.groups()) == EXPECTED_FULL_DATE_GROUPS:
                    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                elif len(match.groups()) == EXPECTED_PARTIAL_DATE_GROUPS:
                    month, day = int(match.group(1)), int(match.group(2))
                    year = current_year
                    if month < current_month:
                        year += 1
                else:
                    continue

                # Extract event content after this date
                start_pos = match.end()
                next_match = None

                for next_pattern in date_patterns:
                    next_search = re.search(next_pattern, container_text[start_pos:])
                    if next_search and (next_match is None or next_search.start() < next_match.start()):
                        next_match = next_search

                if next_match:
                    event_content = container_text[start_pos : start_pos + next_match.start()]
                else:
                    MAX_CONTENT_LENGTH = 500  # noqa: N806
                    event_content = container_text[start_pos : start_pos + MAX_CONTENT_LENGTH]

                event_text = event_content.strip()

                # Extract times from event text
                time_patterns = [
                    r"OPEN\s*(\d{1,2}:\d{2})\s*/\s*START\s*(\d{1,2}:\d{2})",
                    r"開場\s*(\d{1,2}:\d{2})\s*/\s*開演\s*(\d{1,2}:\d{2})",
                    r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
                ]

                open_time = "18:00"  # Default
                start_time = "18:30"  # Default

                for time_pattern in time_patterns:
                    time_match = re.search(time_pattern, event_text, re.IGNORECASE)
                    if time_match:
                        open_time = time_match.group(1)
                        start_time = time_match.group(2)
                        break

                # Extract performers and create schedule
                performers = self._extract_shelter_performers(event_text)
                if performers:
                    schedule = {
                        "date": f"{year}-{month:02d}-{day:02d}",
                        "open_time": open_time,
                        "start_time": start_time,
                        "performers": performers[:10],  # Limit to 10 performers
                    }
                    schedules.append(schedule)

        return schedules

    def find_next_month_link(self, html_content: str) -> str | None:
        """Find the link to next month's schedule page."""
        soup = self.create_soup(html_content)

        # Calculate next month
        current_month = datetime.now().month  # noqa: DTZ001
        current_year = datetime.now().year  # noqa: DTZ001
        next_month = (current_month % 12) + 1
        next_year = current_year if next_month > current_month else current_year + 1

        # Look for next month navigation links (expanded patterns)
        next_patterns = ["翌月", "次月", "next", "→", "次へ", "＞", ">", ">>", "›", "来月"]

        # Search all links
        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True).lower()

            # Skip empty or javascript links
            if not href or href.startswith("javascript:") or href == "#":
                continue

            # Check link text for navigation patterns
            for pattern in next_patterns:
                if pattern.lower() in text:
                    full_url = urljoin(self.website.url, href)
                    logger.debug(f"Found potential next month link by text pattern '{pattern}': {full_url}")
                    return full_url

            # Check href for month indicators
            href_lower = href.lower()
            for pattern in next_patterns:
                if pattern in href_lower:
                    full_url = urljoin(self.website.url, href)
                    logger.debug(f"Found potential next month link in href: {full_url}")
                    return full_url

        # Look for month-specific links (enhanced)
        next_month_patterns = [
            f"{next_month}月",
            f"{next_month:02d}",
            f"{next_year}/{next_month:02d}",
            f"{next_year}-{next_month:02d}",
            f"{next_year}年{next_month}月",
        ]

        for pattern in next_month_patterns:
            for link in links:
                text = link.get_text(strip=True)
                href = link.get("href", "")

                # Check in text or href
                if pattern in text or pattern in href:
                    full_url = urljoin(self.website.url, href)
                    logger.debug(f"Found next month link by date pattern '{pattern}': {full_url}")
                    return full_url

        # Look in pagination or navigation areas
        nav_areas = soup.find_all(["nav", "div", "ul"], class_=re.compile(r"pag|nav|calendar|month", re.IGNORECASE))
        for nav in nav_areas:
            nav_links = nav.find_all("a", href=True)
            for link in nav_links:
                href = link.get("href", "")
                text = link.get_text(strip=True).lower()

                if any(p.lower() in text for p in next_patterns):
                    full_url = urljoin(self.website.url, href)
                    logger.debug(f"Found next month link in navigation area: {full_url}")
                    return full_url

        logger.debug("No next month link found for SHELTER")
        return None

    def _extract_shelter_performers(self, event_text: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performer names from SHELTER event text.

        Handles SHELTER-specific patterns and filters out common non-performer content.
        """
        performers = []

        # Clean up the text
        text = event_text.strip()

        # Remove common non-performer patterns specific to SHELTER
        # Remove day of week names
        text = re.sub(
            r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|月曜|火曜|水曜|木曜|金曜|土曜|日曜)\b",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Remove date and time patterns
        text = re.sub(r"\d{1,2}/\d{1,2}", "", text)
        text = re.sub(r"\d{1,2}:\d{2}", "", text)
        text = re.sub(r"(OPEN|START|開場|開演)", "", text, flags=re.IGNORECASE)

        # Remove price and venue information
        text = re.sub(r"[¥￥]\s*\d+[,\d]*", "", text)
        text = re.sub(r"(会場|料金|チケット|円|door|advance|drink)", "", text, flags=re.IGNORECASE)

        # Remove common SHELTER-specific non-performer phrases
        shelter_noise = [
            r'"[^"]*"',  # Quoted event titles
            r"presents?:?",
            r"(DAY|NIGHT)\s+EVENT",
            r"このイベントの予約は締めきりました。?",
            r"SOLD\s*OUT",
            r"チケット.*",
            r"予約.*",
            r"Release\s+Event",
            r"Digital\s+Single",
            r"1st\s+ALBUM",
            r"NEW\s+ALBUM",
            r"(Japan\s+)?Tour\s+\d{4}",  # Tour 2024, Japan Tour 2026, etc.
            r"vol\.\s*\d+",
            r"#\d+",
            r"Shimokitazawa\s+SHELTER",  # Venue name
            r"SHELTER\s+pre\.",  # SHELTER presents
            r"高校生.*無料",  # High school students free
            r"入場無料",  # Free entry
            r"軽音",  # Light music (club reference)
            r"吹部歓迎",  # Brass band welcome
            r"sans\s*visage",  # Common concatenation issue
        ]

        for pattern in shelter_noise:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Split by common delimiters
        separators = ["\n", "/", "／", "、", "・", "&", "×", "+"]
        delimiter_pattern = "|".join(re.escape(sep) for sep in separators)
        potential_performer_names = re.split(delimiter_pattern, text)

        for performer_name in potential_performer_names:
            cleaned_name = performer_name.strip()

            # Skip if empty or too short
            MIN_PERFORMER_LENGTH = 2  # noqa: N806
            if not cleaned_name or len(cleaned_name) < MIN_PERFORMER_LENGTH:
                continue

            # Skip if it's purely numeric or punctuation
            if cleaned_name.isdigit() or re.match(r"^[^\w]+$", cleaned_name):
                continue

            # Remove brackets and their contents
            cleaned_name = re.sub(r"[\[\(（【].*?[\]\)）】]", "", cleaned_name).strip()

            # Skip common non-performer phrases
            skip_patterns = [
                r"^(and|&|×|\+)$",
                r"^(presents?|pre\.)$",
                r"^\d+$",
                r"^[:\-/\\]+$",
                r"^(event|live|show|concert)$",
                r"^(day|night)$",
                r"^(open|start|door)$",
                r"^(advance|当日|前売)$",
                r"^(sold|out)$",
                r"^(release|tour)$",
                r"^vol\.$",
                r"chart|ranking|single|album",
                r"birthday|anniversary|記念",
                r"festival|フェス",
                r"limited|限定",
                r"tour\s+\d{4}",  # Tour 2024, Tour 2026
                r"japan\s+tour",  # Japan Tour
                r"feels\s+real",  # Event title fragment
                r"Dawn",  # Event name fragment
                r"^.{50,}$",  # Skip very long strings (likely event titles)
            ]

            is_valid = True
            for pattern in skip_patterns:
                if re.search(pattern, cleaned_name, re.IGNORECASE):
                    is_valid = False
                    break

            # Apply additional cleaning
            if is_valid:
                final_name = self._clean_performer_name(cleaned_name)
                MAX_PERFORMER_NAME_LENGTH = 100  # noqa: N806
                if (
                    final_name
                    and self._is_valid_performer_name(final_name)
                    and len(final_name) <= MAX_PERFORMER_NAME_LENGTH
                ):
                    performers.append(final_name)

        # Remove duplicates while preserving order
        seen = set()
        unique_performers = []
        for performer in performers:
            if performer.lower() not in seen:
                seen.add(performer.lower())
                unique_performers.append(performer)

        return unique_performers[:5]  # Limit to 5 performers
