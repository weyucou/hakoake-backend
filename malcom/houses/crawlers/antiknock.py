import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)


@CrawlerRegistry.register("AntiknockCrawler")
class AntiknockCrawler(LiveHouseWebsiteCrawler):
    """
    Specialized crawler for Shinjuku ANTIKNOCK website (https://www.antiknock.net/).

    Handles the specific structure of antiknock's schedule page including:
    - Monthly schedule view with event cards
    - Day/Night event categorization
    - Specific date format (MM/DD)
    - Performer extraction from event titles and descriptions
    """

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915
        """
        Extract performance schedules from antiknock's schedule page.

        Handles the specific structure:
        - Events are in <a> tags with event details
        - Date format: MM/DD with year 2025
        - Day/Night event types
        - Performers listed in event descriptions
        """
        schedules = []
        soup = self.create_soup(html_content)

        try:
            # Find all event links - antiknock uses anchor tags for events
            event_links = soup.find_all("a", href=True)

            for link in event_links:
                href = link.get("href", "")

                # Match antiknock event URL pattern: /schedule/YYYYMMDD/
                event_match = re.search(r"/schedule/(\d{8})/?", href)
                if not event_match:
                    continue

                date_str = event_match.group(1)

                # Parse date: YYYYMMDD -> YYYY-MM-DD
                try:
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])

                    # Validate date
                    current_date = timezone.localdate()
                    current_year = current_date.year
                    next_year = current_year + 1
                    max_month = 12
                    max_day = 31
                    if not (current_year <= year <= next_year and 1 <= month <= max_month and 1 <= day <= max_day):  # noqa: PLR2004
                        continue

                    formatted_date = f"{year}-{month:02d}-{day:02d}"

                except (ValueError, IndexError):
                    continue

                # Extract event information from the link content
                event_text = link.get_text(strip=True)

                # Determine if it's a day or night event
                is_night_event = "NIGHT" in event_text.upper()
                is_day_event = "DAY" in event_text.upper()

                # Set default times based on event type
                if is_night_event:
                    open_time = "18:30"
                    start_time = "19:00"
                elif is_day_event:
                    open_time = "13:30"
                    start_time = "14:00"
                else:
                    # Default to evening show
                    open_time = "18:30"
                    start_time = "19:00"

                # Extract performers from event text
                performers = self._extract_antiknock_performers(event_text)

                # If no performers found or names are truncated (contain "…"), fetch the detail page
                has_truncation = any("…" in p for p in performers)
                event_image_url = None
                if not performers or has_truncation:
                    detail_url = urljoin(self.base_url, href)
                    try:
                        detail_html = self.fetch_page(detail_url)
                        if detail_html:
                            performers = self._extract_performers_from_detail_page(detail_html)
                            logger.debug(f"Extracted performers from detail page: {performers}")
                            event_image_url = self._extract_image_from_detail_page(detail_html)
                    except Exception:  # noqa: BLE001
                        logger.exception(f"Failed to fetch detail page: {detail_url}")

                # Extract additional context for performer validation
                context = event_text

                if performers:
                    schedule_data = {
                        "date": formatted_date,
                        "open_time": open_time,
                        "start_time": start_time,
                        "performers": performers,
                        "context": context,
                        "performance_name": self._extract_event_title(event_text),
                    }
                    if event_image_url:
                        schedule_data["event_image_url"] = event_image_url
                    schedules.append(schedule_data)

                    logger.debug(f"Extracted antiknock event: {formatted_date} - {performers}")

                # Limit to reasonable number of events
                max_events = 30
                if len(schedules) >= max_events:
                    break

            logger.info(f"Extracted {len(schedules)} schedules from antiknock website")

        except Exception:  # noqa: BLE001
            logger.exception("Error extracting antiknock schedules")
            return []
        else:
            return schedules

    def _extract_antiknock_performers(self, event_text: str) -> list[str]:  # noqa: PLR0912, PLR0915
        """
        Extract performer names from antiknock event text.

        Handles patterns like:
        - "PERFORMER1 / PERFORMER2 / PERFORMER3"
        - "ARTIST1・ARTIST2・ARTIST3"
        - "Band Name presents: EVENT TITLE"
        """
        performers = []

        # Clean up the text
        text = event_text.strip()

        # Remove date patterns (MM/DD format)
        text = re.sub(r"\d{2}/\d{2}", "", text)

        # Remove day indicators (TUE, WED, etc.)
        text = re.sub(r"\b(SUN|MON|TUE|WED|THU|FRI|SAT)\b", "", text)

        # Remove event type indicators at the beginning
        text = re.sub(r"^(DAY|NIGHT)", "", text, flags=re.IGNORECASE)

        # Remove presenter information and event production credits
        # Match "pre.", "presents", "制作委員会" etc.
        text = re.sub(r"[^/]+?(制作委員会|presents?|pre\.)[^【]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"ANTIKNOCK\s+presents?:?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"shinjuku\s+ANTIKNOCK\s+presents?", "", text, flags=re.IGNORECASE)

        # Find and extract content within event brackets first to identify actual performers
        bracket_pattern = r"【([^】]+)】"
        bracket_match = re.search(bracket_pattern, text)

        if bracket_match:
            # Remove the bracketed event title from text
            text = re.sub(bracket_pattern, "", text)

            # If the event title contains "presents" or similar, extract performer from before the bracket
            if re.search(r"(presents?|pre\.|制作委員会)", text, re.IGNORECASE):
                # Look for performers after the presenter info but before the event title
                clean_text = text.strip()
            else:
                clean_text = text.strip()
        else:
            clean_text = text.strip()

        # Look for common separators used in performer lists
        separators = [" / ", "/", "・", " × ", "×", " & ", "&", " + ", "+"]

        # Try each separator to split performers
        for separator in separators:
            if separator in clean_text:
                parts = clean_text.split(separator)
                for part in parts:
                    # Additional cleaning for antiknock-specific patterns
                    cleaned_part = part.strip()

                    # Remove any remaining presenter/production info
                    cleaned_part = re.sub(r"^[^a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]*", "", cleaned_part)
                    cleaned_part = re.sub(r"(制作委員会|presents?|pre\.).*", "", cleaned_part, flags=re.IGNORECASE)

                    # Remove Japanese location indicators only (keep country codes like (UK), (USA), (Indonesia))
                    cleaned_part = re.sub(r"\([^)]*[都府県][^)]*\)", "", cleaned_part)  # Remove (Tokyo), (Osaka), etc.

                    # Remove excessive metadata
                    cleaned_part = re.sub(
                        r"(TOUR|tour|ツアー|ALBUM|album|アルバム|RELEASE|release|リリース|SHOW|show|ショー)",
                        "",
                        cleaned_part,
                        flags=re.IGNORECASE,
                    )

                    # Do minimal cleaning instead of using base class _clean_performer_name
                    # which strips closing parentheses
                    cleaned_name = cleaned_part.strip()
                    cleaned_name = re.sub(r"\s+", " ", cleaned_name)

                    # Remove "BAND:" prefix if present
                    cleaned_name = re.sub(r"^BAND:\s*", "", cleaned_name, flags=re.IGNORECASE)

                    max_performer_name_length = 50
                    min_performer_name_length = 2
                    if (
                        cleaned_name
                        and self._is_valid_performer_name(cleaned_name)
                        and min_performer_name_length <= len(cleaned_name) <= max_performer_name_length
                    ):
                        performers.append(cleaned_name)
                break

        # If no separators found, try to extract from the whole text
        if not performers:
            # Clean the entire text as a single performer
            performer_text = clean_text

            # Remove any remaining presenter/production info
            performer_text = re.sub(r"(制作委員会|presents?|pre\.).*", "", performer_text, flags=re.IGNORECASE)
            performer_text = re.sub(
                r"\([^)]*[都府県][^)]*\)", "", performer_text
            )  # Remove Japanese location indicators

            # Do minimal cleaning instead of using base class _clean_performer_name
            cleaned_name = performer_text.strip()
            cleaned_name = re.sub(r"\s+", " ", cleaned_name)

            # Remove "BAND:" prefix if present
            cleaned_name = re.sub(r"^BAND:\s*", "", cleaned_name, flags=re.IGNORECASE)

            max_performer_name_length = 50
            min_performer_name_length = 2
            if (
                cleaned_name
                and self._is_valid_performer_name(cleaned_name)
                and min_performer_name_length <= len(cleaned_name) <= max_performer_name_length
            ):
                performers.append(cleaned_name)

        # Final cleanup and validation
        final_performers = []
        for performer in performers:
            # Skip if it's likely venue/event metadata
            if not any(
                skip_word in performer.lower()
                for skip_word in ["antiknock", "shinjuku", "presents", "pre.", "制作委員会", "vol.", "tour", "ツアー"]
            ):
                min_performer_length = 2
                max_performer_length = 50
                if min_performer_length <= len(performer) <= max_performer_length:  # Reasonable length
                    final_performers.append(performer)

        max_performers = 5
        return final_performers[:max_performers]  # Limit to 5 performers maximum

    def _extract_performers_from_detail_page(self, html_content: str) -> list[str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performer names from antiknock event detail page.

        Looks for performers in the <div class="artist"> section.
        """
        performers = []
        soup = self.create_soup(html_content)

        # Find the artist section
        artist_div = soup.find("div", class_="artist")
        if not artist_div:
            return performers

        # Find the <p> tag containing artist names
        artist_p = artist_div.find("p")
        if not artist_p:
            return performers

        # Get text content and split by <br> tags
        artist_text = artist_p.get_text(separator="\n", strip=True)

        # Split by newlines and clean each performer name
        lines = artist_text.split("\n")
        for line in lines:
            # For detail page, names are already clean, just do minimal cleanup
            # Don't use _clean_performer_name as it strips closing parentheses
            cleaned_name = line.strip()
            if not cleaned_name:
                continue

            # Remove excessive whitespace
            cleaned_name = re.sub(r"\s+", " ", cleaned_name)

            # Remove "BAND:" prefix if present
            cleaned_name = re.sub(r"^BAND:\s*", "", cleaned_name, flags=re.IGNORECASE)

            # Validate and add
            max_performer_name_length = 50
            min_performer_name_length = 2
            if cleaned_name and min_performer_name_length <= len(cleaned_name) <= max_performer_name_length:
                # Skip common non-performer entries and validate alphanumeric content
                skip_words = ["antiknock", "shinjuku", "information", "ticket", "open", "start", "adv", "door"]
                if not any(skip in cleaned_name.lower() for skip in skip_words) and re.search(
                    r"[a-zA-Z0-9\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", cleaned_name
                ):
                    performers.append(cleaned_name)

        max_performers = 10
        return performers[:max_performers]  # Limit to reasonable number

    def _extract_image_from_detail_page(self, html_content: str) -> str | None:
        """Extract event flyer image URL from antiknock detail page."""
        soup = self.create_soup(html_content)
        for img in soup.find_all("img", src=True):
            src = img["src"]
            # Skip small icons/logos; look for flyer-like images
            if any(skip in src.lower() for skip in ["icon", "logo", "arrow", "btn", "button", "nav"]):
                continue
            return urljoin(self.base_url, src)
        return None

    def _extract_event_title(self, event_text: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract event title from antiknock event text."""
        # Look for title in brackets or quotes
        title_patterns = [r"【([^】]+)】", r"「([^」]+)」", r"\[([^\]]+)\]", r'"([^"]+)"', r"'([^']+)'"]

        for pattern in title_patterns:
            match = re.search(pattern, event_text)
            if match:
                title = match.group(1).strip()
                min_title_length = 2
                max_title_length = 100
                if min_title_length < len(title) <= max_title_length:
                    return title

        return None

    def find_next_month_link(self, html_content: str) -> str | None:
        """
        Find next month link for antiknock website.

        Antiknock typically uses navigation arrows or next month links.
        """
        soup = self.create_soup(html_content)

        # Calculate next month
        current_month = datetime.now().month  # noqa: DTZ001
        current_year = datetime.now().year  # noqa: DTZ001
        next_month = (current_month % 12) + 1
        next_year = current_year if next_month > current_month else current_year + 1

        # Look for navigation links with common patterns (expanded)
        nav_patterns = [
            "next",
            "次",
            "翌月",
            "来月",
            "→",
            "＞",
            ">",
            ">>",
            "›",
            "次へ",
            "次月",
        ]

        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href", "")
            text = link.get_text(strip=True).lower()

            # Skip empty, javascript, or anchor links
            if not href or href.startswith("javascript:") or href == "#":
                continue

            # Check if this looks like a next month link
            for pattern in nav_patterns:
                if pattern.lower() in text or pattern in href.lower():
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found potential next month link for Antiknock: {full_url}")
                    return full_url

        # Look for month-specific links
        month_patterns = [
            f"{next_month}月",
            f"{next_month:02d}",
            f"{next_year}/{next_month:02d}",
            f"{next_year}-{next_month:02d}",
            f"{next_year}年{next_month}月",
        ]

        for pattern in month_patterns:
            for link in links:
                text = link.get_text(strip=True)
                href = link.get("href", "")

                # Check in text or href
                if pattern in text or pattern in href:
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found next month link for Antiknock by date pattern '{pattern}': {full_url}")
                    return full_url

        # Look in navigation areas
        nav_areas = soup.find_all(["nav", "div", "ul"], class_=re.compile(r"pag|nav|calendar|month", re.IGNORECASE))
        for nav in nav_areas:
            nav_links = nav.find_all("a", href=True)
            for link in nav_links:
                href = link.get("href", "")
                text = link.get_text(strip=True).lower()

                if any(p.lower() in text for p in nav_patterns):
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found next month link for Antiknock in navigation: {full_url}")
                    return full_url

        logger.debug("No next month link found for Antiknock")
        return None
