import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)


@CrawlerRegistry.register("EggmanCrawler")
class EggmanCrawler(LiveHouseWebsiteCrawler):
    """
    Specialized crawler for eggman live house website.

    Note: This crawler was created without direct access to the website
    due to SSL certificate issues. It uses common patterns found in Japanese
    live house websites.
    """

    def __init__(self, website) -> None:  # noqa: ANN001
        super().__init__(website)
        # Override timeout and add SSL verification bypass for this problematic site
        self.timeout = 30
        self.session.verify = False  # Disable SSL verification for this site

    def extract_live_house_info(self, html_content: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract live house information from the eggman page."""
        soup = self.create_soup(html_content)

        # Initialize with default values
        info = {
            "name": "eggman",
            "name_kana": "エッグマン",
            "name_romaji": "eggman",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": "2000-01-01",
        }

        # Try to extract venue name from title or headers
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.get_text()
            if "eggman" in title_text.lower():
                # Extract any location prefix (e.g., "Shibuya eggman")
                location_match = re.search(
                    r"([\w\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]+)\s*eggman", title_text, re.IGNORECASE
                )
                if location_match:
                    location = location_match.group(1)
                    info["name"] = f"{location} eggman"
                    info["name_romaji"] = f"{location} eggman"

        # Look for venue information in common sections
        info_sections = soup.find_all(["div", "section"], class_=re.compile(r"about|info|access|venue", re.IGNORECASE))

        for section in info_sections:
            section_text = section.get_text()

            # Extract address
            address_patterns = [
                r"〒?\d{3}-?\d{4}\s*([^0-9\n]{5,50})",
                r"(東京都[^0-9\n]{5,40})",
                r"([\u4E00-\u9FAF]+[都道府県][^0-9\n]{5,40})",
            ]

            for pattern in address_patterns:
                address_match = re.search(pattern, section_text)
                if address_match:
                    info["address"] = address_match.group(1).strip()
                    break

            # Extract phone number
            phone_patterns = [
                r"(?:TEL|電話|Phone)[：:\s]*(\d{2,4}[-‐]\d{3,4}[-‐]\d{3,4})",
                r"(\d{2,4}[-‐]\d{3,4}[-‐]\d{3,4})",
            ]

            for pattern in phone_patterns:
                phone_match = re.search(pattern, section_text)
                if phone_match:
                    info["phone_number"] = phone_match.group(1).strip()
                    break

            # Extract capacity
            capacity_patterns = [
                r"(?:キャパ|キャパシティ|収容|定員)[：:\s]*(\d+)",
                r"(\d+)\s*(?:人|名|persons?)",
                r"capacity[：:\s]*(\d+)",
            ]

            for pattern in capacity_patterns:
                capacity_match = re.search(pattern, section_text, re.IGNORECASE)
                if capacity_match:
                    capacity = int(capacity_match.group(1))
                    if 50 <= capacity <= 2000:  # Reasonable range  # noqa: PLR2004
                        info["capacity"] = capacity
                        break

        return info

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performance schedules from the eggman schedule page."""
        soup = self.create_soup(html_content)
        schedules = []

        # Extract year and month from the month header
        month_header = soup.find("div", class_="monthHeader")
        current_year = datetime.now().year  # noqa: DTZ001
        current_month = datetime.now().month  # noqa: DTZ001

        if month_header:
            h1 = month_header.find("h1")  # noqa: PLR2004
            if h1:
                # Format: 2025.07
                year_month_match = re.search(r"(\d{4})\.(\d{2})", h1.get_text())
                if year_month_match:
                    current_year = int(year_month_match.group(1))
                    current_month = int(year_month_match.group(2))

        # Find all schedule articles
        schedule_articles = soup.find_all("article", class_="scheduleList")

        for article in schedule_articles:
            # Extract day from time element
            time_elem = article.find("time")
            if not time_elem:
                continue

            day_elem = time_elem.find("strong")
            if not day_elem:
                continue

            day = int(day_elem.get_text().strip())

            # Build the date
            date_str = f"{current_year}-{current_month:02d}-{day:02d}"

            # Extract event title
            h1 = article.find("h1")
            performance_name = ""
            if h1:
                performance_name = h1.get_text().strip()

            # Extract times
            open_time = "18:30"
            start_time = "19:00"

            body_elem = article.find("div", class_="scheListBody")
            if body_elem:
                li_elements = body_elem.find_all("li")
                for li in li_elements:
                    text = li.get_text()
                    if "OPEN" in text:
                        time_match = re.search(r"(\d{1,2}:\d{2})", text)
                        if time_match:
                            open_time = time_match.group(1)
                    elif "START" in text:
                        time_match = re.search(r"(\d{1,2}:\d{2})", text)
                        if time_match:
                            start_time = time_match.group(1)

            # Extract performers from the act div
            performers = []
            act_div = article.find("div", class_="act")
            if act_div:
                act_text = act_div.get_text()

                # Remove common prefixes
                act_text = re.sub(r"^\s*\(\s*50音順\s*\)\s*:\s*", "", act_text)
                act_text = re.sub(r"^\s*ACT\s*:\s*", "", act_text, flags=re.IGNORECASE)

                # Split by common delimiters
                # Handle both / and space as delimiters for names
                performer_names = re.split(r"\s*/\s*|\s+/\s+", act_text)

                for name in performer_names:
                    cleaned = self._clean_performer_name(name.strip())
                    if cleaned and self._is_valid_performer_name(cleaned):
                        performers.append(cleaned)

            # Get full context for ticket info extraction
            context = article.get_text()

            if performers or performance_name:
                schedule = {
                    "date": date_str,
                    "open_time": open_time,
                    "start_time": start_time,
                    "performers": performers if performers else [performance_name],
                    "context": context,
                    "performance_name": performance_name,
                }
                schedules.append(schedule)

        return schedules

    def _extract_performers_from_context(self, context: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract performer names from context text."""
        performers = []

        # Clean the context
        cleaned_context = context

        # Remove common non-performer elements
        noise_patterns = [
            r"[¥￥]\s*\d+[,\d]*",  # Prices
            r"\d{1,2}[:：]\d{2}",  # Times
            r"(?:OPEN|START|開場|開演)[：:\s]*",  # Time labels
            r"(?:前売|当日|ADV|DOOR)[：:\s]*",  # Ticket types
            r"\+\d*D",  # Drink charges
            r"[（(][月火水木金土日][）)]",  # Day of week
        ]

        for pattern in noise_patterns:
            cleaned_context = re.sub(pattern, "", cleaned_context, flags=re.IGNORECASE)

        # Look for performer listings
        performer_section_patterns = [
            r"(?:出演|ACT|LIVE|ARTIST|PERFORMER)[：:\s]*([^\n]+)",
            r"(?:w/|with|feat\.?)[：:\s]*([^\n]+)",
        ]

        performer_text = ""
        for pattern in performer_section_patterns:
            match = re.search(pattern, cleaned_context, re.IGNORECASE)
            if match:
                performer_text = match.group(1)
                break

        if not performer_text:
            # Try to extract from the whole context
            performer_text = cleaned_context

        # Split by common delimiters
        delimiters = [" / ", "／", "、", "・", " & ", "＆", " × ", "×", " + ", "＋"]

        # Start with the full text
        potential_performers = [performer_text]

        # Split by each delimiter
        for delimiter in delimiters:
            new_performers = []
            for text in potential_performers:
                parts = text.split(delimiter)
                new_performers.extend(parts)
            potential_performers = new_performers

        # Clean and validate each potential performer
        for performer in potential_performers:
            cleaned = self._clean_performer_name(performer.strip())
            if cleaned and self._is_valid_performer_name(cleaned):
                performers.append(cleaned)

        # Limit to reasonable number
        return performers[:10]

    def find_next_month_link(self, html_content: str) -> str | None:  # noqa: C901, PLR0912
        """Find the link to next month's schedule."""
        soup = self.create_soup(html_content)

        # Calculate next month
        current_date = timezone.localdate()
        next_month = (current_date.month % 12) + 1
        next_year = current_date.year if next_month > current_date.month else current_date.year + 1

        # Navigation patterns (expanded)
        next_patterns = [
            "next",
            "次",
            "翌月",
            "来月",
            ">>",
            "→",
            "＞",
            "次へ",
            "次月",
            "next month",
            ">",
            "›",
        ]

        # Check all links
        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True).lower()

            # Skip javascript and anchors
            if not href or href.startswith(("#", "javascript:")):
                continue

            # Check text for navigation patterns
            for pattern in next_patterns:
                if pattern.lower() in text:
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found potential next month link for Eggman by text: {full_url}")
                    return full_url

            # Check href for navigation patterns
            href_lower = href.lower()
            for pattern in next_patterns:
                if pattern in href_lower:
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found potential next month link for Eggman in href: {full_url}")
                    return full_url

        # Look for month-based navigation (enhanced)
        month_patterns = [
            f"{next_year}/{next_month:02d}",
            f"{next_year}-{next_month:02d}",
            f"{next_year}年{next_month}月",
            f"{next_month}月",
            f"{next_month:02d}",
        ]

        for pattern in month_patterns:
            for link in links:
                text = link.get_text(strip=True)
                href = link.get("href", "")

                # Skip javascript and anchors
                if not href or href.startswith(("#", "javascript:")):
                    continue

                # Check in text or href
                if pattern in text or pattern in href:
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found next month link for Eggman by date pattern '{pattern}': {full_url}")
                    return full_url

        # Look in navigation areas
        nav_areas = soup.find_all(["nav", "div", "ul"], class_=re.compile(r"pag|nav|calendar|month", re.IGNORECASE))
        for nav in nav_areas:
            nav_links = nav.find_all("a", href=True)
            for link in nav_links:
                href = link.get("href", "")
                text = link.get_text(strip=True).lower()

                if not href or href.startswith(("#", "javascript:")):
                    continue

                if any(p.lower() in text for p in next_patterns):
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found next month link for Eggman in navigation: {full_url}")
                    return full_url

        logger.debug("No next month link found for Eggman")
        return None
