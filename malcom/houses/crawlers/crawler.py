import logging
import re
from abc import ABC
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from performers.models import Performer, PerformerSocialLink
from performers.normalization import find_existing_performer
from pykakasi import kakasi

from ..definitions import YEAR_LOOKAHEAD, YEAR_LOOKBACK, CrawlerCollectionState, WebsiteProcessingState
from ..models import LiveHouse, LiveHouseWebsite, PerformanceSchedule, PerformanceScheduleTicketPurchaseInfo

logger = logging.getLogger(__name__)


def parse_japanese_time(time_str: str) -> tuple[time | None, int]:
    """
    Parse time strings including Japanese late-night notation (24:00+).

    Japanese venues use times like '24:00' (midnight), '25:00' (1am), etc.
    to indicate late-night shows continuing past midnight.

    Returns:
        Tuple of (time, days_offset) where days_offset is the number of days
        to add to the associated date. Returns (None, 0) if parsing fails.

    Examples:
        '18:30' -> (time(18, 30), 0)
        '24:00' -> (time(0, 0), 1)   # midnight next day
        '25:30' -> (time(1, 30), 1)  # 1:30 AM next day
    """
    if not time_str or not isinstance(time_str, str):
        return None, 0

    time_str = time_str.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if not match:
        return None, 0

    hour = int(match.group(1))
    minute = int(match.group(2))

    # Calculate days offset for hours >= 24
    days_offset = hour // 24
    hour = hour % 24

    try:
        parsed_time = datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()  # noqa: DTZ007
    except ValueError:
        return None, 0
    else:
        return parsed_time, days_offset


class PerformerValidationError(ValueError):
    """Raised when a performer fails validation as a legitimate artist."""


class CrawlerRegistry:
    """Registry to manage crawler classes."""

    _crawlers = {}

    @classmethod
    def register(cls, crawler_name: str) -> Callable[[type], type]:
        """Decorator to register a crawler class."""

        def decorator(crawler_class: type) -> type:
            cls._crawlers[crawler_name] = crawler_class
            return crawler_class

        return decorator

    @classmethod
    def get_crawler(cls, crawler_name: str) -> type | None:
        """Get a crawler class by name."""
        return cls._crawlers.get(crawler_name)

    @classmethod
    def run_crawler(cls, website: LiveHouseWebsite) -> None:
        """Run the appropriate crawler for a website."""
        crawler_class = cls.get_crawler(website.crawler_class)
        if crawler_class:
            crawler = crawler_class(website)
            crawler.run()
        else:
            msg = f"No crawler found for class: {website.crawler_class}"
            raise ValueError(msg)  # noqa: B904


@CrawlerRegistry.register("LiveHouseWebsiteCrawler")
class LiveHouseWebsiteCrawler(ABC):  # noqa: B024
    """Base class for live house website crawlers."""

    def __init__(self, website: LiveHouseWebsite) -> None:
        self.website = website
        self.base_url = website.url
        self.session = requests.Session()
        # Set timeout for all requests
        self.timeout = 30  # 30 seconds timeout

    def run(self) -> None:
        """Main method to run the crawler for a specific website."""
        logger.info(f"Starting crawler for: {self.website.url}")

        # Update state to in_progress (outside transaction so it persists)
        self.website.state = WebsiteProcessingState.IN_PROGRESS
        self.website.save()

        try:
            with transaction.atomic():
                # Fetch main page
                logger.debug(f"Fetching main page: {self.website.url}")
                main_page_content = self.fetch_page(self.website.url)
                logger.debug(f"Fetched {len(main_page_content)} characters from main page")

                # Extract live house information
                logger.debug("Extracting live house info")
                live_house_data = self.extract_live_house_info(main_page_content)
                logger.debug(f"Extracted live house data: {live_house_data}")

                # Create or update LiveHouse instance
                live_house = self.create_or_update_live_house(live_house_data)
                logger.info(f"Created/updated LiveHouse: {live_house.name}")

                # Find schedule page link
                logger.debug("Finding schedule page link")
                schedule_url = self.find_schedule_link(main_page_content)
                logger.debug(f"Schedule URL found: {schedule_url}")

                if schedule_url:
                    # Fetch and parse performance schedules
                    logger.info(f"Processing schedules from: {schedule_url}")
                    self.process_performance_schedules(schedule_url, live_house)
                else:
                    logger.warning("No schedule URL found")

                # Update last collected datetime and state for the live house
                live_house.last_collected_datetime = timezone.now()
                live_house.last_collection_state = CrawlerCollectionState.SUCCESS
                live_house.save()

            # Update state to completed (outside transaction so it persists)
            self.website.state = WebsiteProcessingState.COMPLETED
            self.website.save()
            logger.info(f"Successfully completed crawling: {self.website.url}")

        except requests.Timeout:
            # Handle timeout specifically (outside transaction so state persists)
            logger.exception(f"Timeout while crawling {self.website.url}")
            self.website.state = WebsiteProcessingState.FAILED
            self.website.save()

        except Exception:  # noqa: BLE001
            # Handle all other errors (outside transaction so state persists)
            logger.exception(f"Error while crawling {self.website.url}")
            self.website.state = WebsiteProcessingState.FAILED
            self.website.save()

    def fetch_page(self, url: str) -> str:
        """Fetch the content of a page from the given URL."""
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def fetch_page_js(
        self,
        url: str,
        wait_for_selector: str | None = None,
        click_load_more: bool = False,
        load_more_selector: str = "button:has-text('Load More'), button:has-text('もっと見る')",
        max_clicks: int = 10,
    ) -> str:
        """
        Fetch page content using Playwright for JavaScript-rendered content.

        Args:
            url: URL to fetch
            wait_for_selector: CSS selector to wait for before capturing (optional)
            click_load_more: Whether to click "Load More" buttons until they disappear
            load_more_selector: CSS selector for "Load More" button
            max_clicks: Maximum number of times to click "Load More" (safety limit)

        Returns:
            Rendered HTML content after JavaScript execution
        """
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        logger.debug(f"Fetching page with Playwright: {url}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                page.goto(url, timeout=self.timeout * 1000)

                # Wait for specific selector if provided
                if wait_for_selector:
                    logger.debug(f"Waiting for selector: {wait_for_selector}")
                    page.wait_for_selector(wait_for_selector, timeout=self.timeout * 1000)

                # Click "Load More" button repeatedly if requested
                if click_load_more:
                    clicks = 0
                    while clicks < max_clicks:
                        try:
                            # Check if load more button is visible
                            if page.is_visible(load_more_selector, timeout=2000):
                                logger.debug(f"Clicking load more button (click {clicks + 1})")
                                page.click(load_more_selector)
                                # Wait for new content to load
                                page.wait_for_timeout(1500)
                                clicks += 1
                            else:
                                logger.debug("Load more button not found, stopping")
                                break
                        except Exception:  # noqa: BLE001
                            logger.debug("Load more button no longer available")
                            break

                    if clicks > 0:
                        logger.debug(f"Clicked load more button {clicks} times")

                return page.content()
            finally:
                context.close()
                browser.close()

    def create_soup(self, html_content: str) -> BeautifulSoup:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Create a BeautifulSoup object from HTML content."""
        return BeautifulSoup(html_content, "html.parser")

    def extract_live_house_info(self, html_content: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract live house information from the main page.
        Must return a dict with keys: name, name_kana, name_romaji, address, phone_number, capacity, opened_date

        Default implementation uses existing LiveHouse data and tries to extract additional info.
        Subclasses can override for site-specific logic.
        """
        return self._generic_extract_live_house_info(html_content)

    def find_schedule_link(self, html_content: str) -> str | None:
        """
        Find the link to the schedule page.

        First checks the schedule_url field on the website model.
        Falls back to generic HTML-based schedule link discovery.
        Subclasses can override for site-specific logic (e.g. dynamic date-based URLs).
        """
        if self.website.schedule_url:
            logger.debug(f"Using stored schedule_url: {self.website.schedule_url}")
            return self.website.schedule_url
        return self._generic_find_schedule_link(html_content)

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract performance schedule information from schedule page.
        Must return a list of dicts with keys: date, open_time, start_time, performers

        Default implementation uses generic date/time pattern matching.
        Subclasses can override for site-specific logic.
        """
        return self._generic_extract_performance_schedules(html_content)

    def extract_ticket_info(self, html_content: str, context: str = "") -> PerformanceScheduleTicketPurchaseInfo | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Extract ticket information from schedule page or event context.
        Returns a PerformanceScheduleTicketPurchaseInfo object (not saved to DB yet).

        Default implementation uses generic pattern matching.
        Subclasses can override for site-specific logic.
        """
        return self._extract_ticket_info(html_content, context)

    def create_or_update_live_house(self, data: dict[str, str]) -> LiveHouse:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Create or update a LiveHouse instance."""
        # Convert string date to date object if needed
        opened_date = data.get("opened_date")
        if isinstance(opened_date, str) and opened_date:
            opened_date = datetime.strptime(opened_date, "%Y-%m-%d").date()  # noqa: DTZ007
        elif not opened_date:
            # Default to a reasonable date if not found
            opened_date = date(2000, 1, 1)

        live_house, created = LiveHouse.objects.update_or_create(
            website=self.website,
            defaults={
                "name": data["name"],
                "name_kana": data.get("name_kana", ""),
                "name_romaji": data.get("name_romaji", ""),
                "address": data.get("address", ""),
                "phone_number": data.get("phone_number", ""),
                "capacity": int(data.get("capacity", 0)),
                "opened_date": opened_date,
            },
        )
        return live_house

    def process_performance_schedules(self, schedule_url: str, live_house: LiveHouse) -> None:
        """Process performance schedules including page traversal for multiple months."""
        logger.debug(f"Fetching schedule page: {schedule_url}")
        # Get current and next month pages
        current_month_content = self.fetch_page(schedule_url)
        logger.debug(f"Fetched {len(current_month_content)} characters from schedule page")

        schedules = self.extract_performance_schedules(current_month_content)
        logger.info(f"Extracted {len(schedules)} schedules from current month")

        # Try to find next month link
        next_month_url = self.find_next_month_link(current_month_content)
        logger.debug(f"Next month URL: {next_month_url}")

        if next_month_url:
            try:
                logger.debug(f"Fetching next month page: {next_month_url}")
                next_month_content = self.fetch_page(next_month_url)
                next_month_schedules = self.extract_performance_schedules(next_month_content)
                logger.info(f"Extracted {len(next_month_schedules)} schedules from next month")
                schedules.extend(next_month_schedules)
            except requests.HTTPError as e:
                logger.warning(f"Failed to fetch next month page (HTTP {e.response.status_code}): {next_month_url}")
                logger.debug("Continuing with current month schedules only")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Error fetching next month page: {e}")
                logger.debug("Continuing with current month schedules only")

        logger.info(f"Creating {len(schedules)} performance schedule records")
        # Create PerformanceSchedule instances
        created_count = 0
        total_performers = set()

        for schedule_data in schedules:
            try:
                performance = self.create_performance_schedule(live_house, schedule_data)
                created_count += 1

                # Count performers for this schedule
                schedule_performers = performance.performers.all()
                for performer in schedule_performers:
                    total_performers.add(performer.name)

                perf_names = ", ".join([p.name for p in schedule_performers])
                logger.debug(f"Created schedule: {performance.performance_date} - {perf_names}")
            except Exception:  # noqa: BLE001
                logger.exception(f"Failed to create schedule for {schedule_data}")

        logger.info(f"📊 COLLECTION SUMMARY for {live_house.name}:")
        logger.info(f"  ✅ Performance Schedules: {created_count} created")
        logger.info(f"  🎭 Unique Performers: {len(total_performers)} discovered")
        logger.info(f"  🎪 Venue: {live_house.name} ({live_house.capacity} capacity)")

        if total_performers:
            performer_list = list(total_performers)[:5]  # Show first 5
            performers_text = ", ".join(performer_list)
            if len(total_performers) > 5:  # noqa: PLR2004
                performers_text += f" + {len(total_performers) - 5} more"
            logger.info(f"  🎵 Featured Artists: {performers_text}")

        logger.info(f"Successfully created {created_count} performance schedules")

    def find_next_month_link(self, html_content: str) -> str | None:
        """
        Find the link to next month's schedule page.

        Default implementation looks for common next month keywords.
        Subclasses can override for site-specific logic.
        """
        return self._generic_find_next_month_link(html_content)

    def create_performance_schedule(self, live_house: LiveHouse, data: dict) -> PerformanceSchedule:
        """Create a PerformanceSchedule instance with ticket information."""
        perf_date, open_time, start_time = self._parse_schedule_times(data)
        clean_names = self._preprocess_performer_names(data.get("performers", []))
        valid_performers = self._validate_performers(clean_names, live_house, perf_date)
        performance = self._create_or_get_schedule(live_house, perf_date, open_time, start_time, data)
        self._save_and_link_performers(performance, valid_performers)
        self._extract_and_save_ticket_info(performance, data)
        return performance

    def _parse_schedule_times(self, data: dict) -> tuple[date, time | None, time | None]:
        """Parse and convert date/time fields from schedule data."""
        performance_date = data["date"]
        if isinstance(performance_date, str):
            performance_date = datetime.strptime(performance_date, "%Y-%m-%d").date()  # noqa: DTZ007

        open_time = data["open_time"]
        if isinstance(open_time, str):
            open_time, _ = parse_japanese_time(open_time)
            if open_time is None:
                logger.warning(f"Unparsable open_time value: '{data['open_time']}' - setting to None")

        start_time = data["start_time"]
        start_time_days_offset = 0
        if isinstance(start_time, str):
            start_time, start_time_days_offset = parse_japanese_time(start_time)
            if start_time is None:
                logger.warning(f"Unparsable start_time value: '{data['start_time']}' - setting to None")

        # Adjust performance_date if start_time was >= 24:00 (e.g., '24:00' means next day)
        if start_time_days_offset > 0:
            performance_date = performance_date + timedelta(days=start_time_days_offset)

        return performance_date, open_time, start_time

    def _preprocess_performer_names(self, performer_names: list[str] | str) -> list[str]:
        """Split, clean, and filter performer names."""
        if isinstance(performer_names, str):
            performer_names = re.split(r"[,、/／]", performer_names)
            performer_names = [name.strip() for name in performer_names if name.strip()]

        clean_names = []
        for name in performer_names:
            cleaned_name = self._clean_performer_name(name)
            if cleaned_name and self._is_valid_performer_name(cleaned_name):
                clean_names.append(cleaned_name)
        return clean_names

    def _validate_performers(
        self, clean_names: list[str], live_house: LiveHouse, performance_date: date
    ) -> list[Performer]:
        """Validate all performers and return list of valid Performer objects (some unsaved)."""
        valid_performers: list[Performer] = []
        for performer_name in clean_names:
            existing_performer = find_existing_performer(performer_name)
            if existing_performer:
                valid_performers.append(existing_performer)
                logger.debug(f"✅ Using existing validated performer: {performer_name}")
                continue

            # New performer - validate BEFORE creating in DB
            logger.debug(f"🔍 Validating new performer: {performer_name}")
            kks = kakasi()
            result = kks.convert(performer_name)
            performer = Performer(
                name=performer_name,
                name_kana="".join([item["kana"] for item in result]),
                name_romaji="".join([item["hepburn"] for item in result]),
            )

            try:
                self._search_for_performer_details(performer)
                valid_performers.append(performer)
                logger.info(f"✅ Validated new performer: {performer_name}")
            except PerformerValidationError:
                logger.error(  # noqa: TRY400
                    f"❌ Skipping performer '{performer_name}' for "
                    f"[{live_house.id}] {live_house.name} on {performance_date}"
                )
            except Exception as e:  # noqa: BLE001
                logger.exception(
                    f"❌ Failed to process performer '{performer_name}' for {live_house.name} "
                    f"on {performance_date}: {e}"  # noqa: TRY401
                )

        if not valid_performers:
            logger.warning(
                f"⚠️ Skipping schedule for {live_house.name} on {performance_date}: No valid performers found"
            )
            raise ValueError("No valid performers for this schedule")  # noqa: B904

        return valid_performers

    def _create_or_get_schedule(
        self,
        live_house: LiveHouse,
        performance_date: date,
        open_time: time | None,
        start_time: time | None,
        data: dict,
    ) -> PerformanceSchedule:
        """Create or retrieve the PerformanceSchedule record."""
        defaults: dict = {"open_time": open_time}
        if "performance_name" in data and data["performance_name"]:
            defaults["performance_name"] = data["performance_name"]

        performance, _created = PerformanceSchedule.objects.get_or_create(
            live_house=live_house, performance_date=performance_date, start_time=start_time, defaults=defaults
        )
        return performance

    def _save_and_link_performers(self, performance: PerformanceSchedule, valid_performers: list[Performer]) -> None:
        """Save new performers to DB and link all valid performers to the schedule."""
        for performer in valid_performers:
            if performer.pk is None:  # New performer not yet saved
                matched = find_existing_performer(performer.name)
                if matched:
                    performer = matched  # noqa: PLW2901
                else:
                    defaults = {
                        "name": performer.name,
                        "name_kana": performer.name_kana,
                    }
                    if hasattr(performer, "website") and performer.website:
                        defaults["website"] = performer.website

                    existing_performer, created = Performer.objects.get_or_create(
                        name_romaji=performer.name_romaji, defaults=defaults
                    )
                    if created:
                        logger.info(f"✅ Created performer in database: {existing_performer.name}")
                    else:
                        logger.info(
                            f"ℹ️ Using existing performer with same romaji: {existing_performer.name} "
                            f"(requested: {performer.name}, romaji: {performer.name_romaji})"
                        )
                    performer = existing_performer  # noqa: PLW2901
            performance.performers.add(performer)

    def _extract_and_save_ticket_info(self, performance: PerformanceSchedule, data: dict) -> None:
        """Extract ticket information from context and save it."""
        if "context" in data:
            ticket_info = self.extract_ticket_info("", data["context"])
            if ticket_info:
                self._create_or_update_ticket_info(performance, ticket_info)

    # Generic helper methods that concrete implementations can use
    def _generic_extract_live_house_info(self, html_content: str) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915
        """
        Generic helper method to extract live house information.
        Uses existing LiveHouse instance and tries to extract additional info from the page.
        """
        soup = self.create_soup(html_content)

        # Get existing LiveHouse instance
        existing_livehouse = self.website.live_houses.first()
        if not existing_livehouse:
            raise ValueError(f"No LiveHouse entry found for website {self.website.url}")  # noqa: B904

        # Try to extract additional information from the page
        page_text = soup.get_text()

        # Try to find address if not set
        if not existing_livehouse.address:
            address_patterns = [
                r"[〒]\s*(\d{3}-\d{4})\s*([^0-9\n]{10,50})",
                r"住所[：:\s]*([^0-9\n]{10,50})",
                r"Address[：:\s]*([^0-9\n]{10,50})",
                r"(東京都[^0-9\n]{5,40})",
            ]

            for pattern in address_patterns:
                match = re.search(pattern, page_text)
                if match:
                    if len(match.groups()) > 1:
                        existing_livehouse.address = match.group(2).strip()
                    elif len(match.groups()) == 1:
                        existing_livehouse.address = match.group(1).strip()
                    else:
                        # No capturing groups, use entire match
                        existing_livehouse.address = match.group(0).strip()
                    break

        # Try to find phone number if not set
        if not existing_livehouse.phone_number:
            phone_patterns = [
                r"(?:電話|TEL|Phone)[：:\s]*(\d{2,4}[-‐]\d{3,4}[-‐]\d{3,4})",
                r"(\d{2,4}[-‐]\d{3,4}[-‐]\d{3,4})",
            ]

            for pattern in phone_patterns:
                match = re.search(pattern, page_text)
                if match:
                    existing_livehouse.phone_number = match.group(1).strip()
                    break

        # Try to find capacity if not set
        if existing_livehouse.capacity == 0:
            capacity_patterns = [
                r"(?:キャパ|キャパシティ|収容)[：:\s]*(\d+)",
                r"(?:capacity|Capacity)[：:\s]*(\d+)",
                r"(\d+)\s*(?:人|名|persons?)",
            ]

            for pattern in capacity_patterns:
                match = re.search(pattern, page_text)
                if match:
                    capacity = int(match.group(1))
                    if 50 <= capacity <= 2000:  # Reasonable range for live houses  # noqa: PLR2004
                        existing_livehouse.capacity = capacity
                        break

        # Return the data in the expected format for create_or_update_live_house
        return {
            "name": existing_livehouse.name,
            "name_kana": existing_livehouse.name_kana,
            "name_romaji": existing_livehouse.name_romaji,
            "address": existing_livehouse.address,
            "phone_number": existing_livehouse.phone_number,
            "capacity": str(existing_livehouse.capacity),
            "opened_date": existing_livehouse.opened_date.strftime("%Y-%m-%d"),
        }

    def _generic_find_schedule_link(self, html_content: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Generic helper method to find schedule page link."""
        soup = self.create_soup(html_content)

        # Look for schedule-related links
        schedule_keywords = [
            "schedule",
            "スケジュール",
            "live",
            "ライブ",
            "event",
            "イベント",
            "calendar",
            "カレンダー",
        ]

        links = soup.find_all("a", href=True)
        for link in links:
            href = link.get("href")
            text = link.get_text().lower()

            for keyword in schedule_keywords:
                if keyword in text or keyword in href.lower():
                    return urljoin(self.base_url, href)

        # Also check for navigation menus
        nav_elements = soup.find_all(["nav", "ul", "div"], class_=re.compile(r"(menu|nav|header)", re.IGNORECASE))
        for nav in nav_elements:
            nav_links = nav.find_all("a", href=True)
            for link in nav_links:
                href = link.get("href")
                text = link.get_text().lower()

                for keyword in schedule_keywords:
                    if keyword in text:
                        return urljoin(self.base_url, href)

        return None

    def _generic_extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915
        """Generic helper method to extract performance schedules."""
        schedules = []
        soup = self.create_soup(html_content)

        # Look for date patterns in the content
        text = soup.get_text()

        # Common date patterns for Japanese websites
        date_patterns = [
            r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?",
            r"(\d{1,2})[月/-](\d{1,2})[日]?",
            r"(\d{4})-(\d{1,2})-(\d{1,2})",
        ]

        today = timezone.localdate()
        current_year = today.year
        current_month = today.month
        found_dates = set()

        for pattern in date_patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                groups = match.groups()

                if len(groups) == 3:  # Year, month, day  # noqa: PLR2004
                    year, month, day = groups
                elif len(groups) == 2:  # Month, day (infer year)  # noqa: PLR2004
                    month, day = groups
                    month_int = int(month)
                    # If current month is late in the year and parsed month is early,
                    # assume it belongs to next year (e.g. December page showing January dates)
                    if current_month >= 11 and month_int <= 2:  # noqa: PLR2004
                        year = str(current_year + 1)
                    else:
                        year = str(current_year)
                else:
                    continue

                try:
                    year_int = int(year)
                    month_int = int(month)
                    day_int = int(day)

                    # Validate date ranges
                    min_year = current_year - YEAR_LOOKBACK
                    max_year = current_year + YEAR_LOOKAHEAD
                    if min_year <= year_int <= max_year and 1 <= month_int <= 12 and 1 <= day_int <= 31:  # noqa: PLR2004
                        date_str = f"{year_int}-{month_int:02d}-{day_int:02d}"
                        if date_str not in found_dates:
                            found_dates.add(date_str)

                            # Try to find time information near this date
                            context_start = max(0, match.start() - 200)
                            context_end = min(len(text), match.end() + 200)
                            context = text[context_start:context_end]

                            # Look for time patterns
                            time_match = re.search(r"(\d{1,2}):(\d{2})", context)
                            if time_match:
                                start_time = f"{time_match.group(1).zfill(2)}:{time_match.group(2)}"
                            else:
                                start_time = "19:00"  # Default

                            # Extract performer/event info from context
                            performers = []
                            # Look for artist names or event titles in the context
                            lines = context.split("\n")
                            for raw_line in lines:
                                cleaned_line = raw_line.strip()
                                if (
                                    cleaned_line
                                    and not re.match(r"^[\d\s/:.-]+$", cleaned_line)
                                    and len(cleaned_line) > 2  # noqa: PLR2004
                                ):  # noqa: PLR2004, E501
                                    # This might be a performer or event name
                                    performers.append(cleaned_line[:50])  # Limit length
                                    if len(performers) >= 3:  # noqa: PLR2004  # Limit to 3 performers
                                        break

                            if not performers:
                                performers = ["Live Event"]

                            schedules.append(
                                {
                                    "date": date_str,
                                    "open_time": "18:30",  # Default
                                    "start_time": start_time,
                                    "performers": performers[:3],  # Max 3 performers
                                }
                            )

                            # Limit to reasonable number of schedules
                            if len(schedules) >= 20:  # noqa: PLR2004
                                break

                except (ValueError, IndexError):
                    continue

        return schedules[:20]  # Return max 20 schedules

    def _generic_find_next_month_link(self, html_content: str) -> str | None:  # noqa: C901, PLR0912, PLR0915
        """
        Generic helper method to find next month link.

        Uses multiple strategies to find next month navigation:
        - Text and href pattern matching
        - Year-aware date-based patterns
        - Navigation area targeting
        """
        soup = self.create_soup(html_content)

        # Calculate next month with year-aware logic
        current_date = timezone.localdate()
        next_month = (current_date.month % 12) + 1
        next_year = current_date.year if next_month > current_date.month else current_date.year + 1

        # Expanded navigation patterns
        next_patterns = [
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
            "next month",
            "forward",
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
                    logger.debug(f"Found potential next month link by text pattern '{pattern}': {full_url}")
                    return full_url

            # Check href for navigation patterns
            href_lower = href.lower()
            for pattern in next_patterns:
                if pattern in href_lower:
                    full_url = urljoin(self.base_url, href)
                    logger.debug(f"Found potential next month link in href: {full_url}")
                    return full_url

        # Look for month-based navigation with year awareness
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
                    logger.debug(f"Found next month link by date pattern '{pattern}': {full_url}")
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
                    logger.debug(f"Found next month link in navigation area: {full_url}")
                    return full_url

        logger.debug("No next month link found")
        return None

    def _clean_performer_name(self, name: str) -> str:
        """Clean and normalize performer name for Japanese performers."""
        if not name:
            return ""

        # Strip BOM and whitespace
        name = name.strip("\ufeff")

        # Strip "and more" suffixes
        name = re.sub(r"\s*(?:\.{0,3}|…)\s*and\s+more.*$", "", name, flags=re.IGNORECASE)

        # Remove common prefixes/suffixes that aren't part of performer names
        name = name.strip()

        # Remove pricing information
        name = re.sub(r"[¥￥]\s*\d+[,\d]*", "", name)

        # Remove time information
        name = re.sub(r"\d{1,2}:\d{2}", "", name)

        # Remove drink charge information
        name = re.sub(r"\(.*1D.*\)", "", name)
        name = re.sub(r"\+1D", "", name)
        name = re.sub(r"入場時別途1D", "", name)

        # Remove day of week indicators
        name = re.sub(r"[（(][月火水木金土日][）)]", "", name)

        # Remove excessive whitespace and clean up
        name = re.sub(r"\s+", " ", name)
        name = name.strip("- /\\()[]{}、。")

        return name.strip()

    def _extract_open_start_times(self, text: str) -> dict[str, str | None]:
        """Extract OPEN/START times from text using common Japanese live house patterns.

        Tries English patterns (OPEN/START), Japanese patterns (開場/開演),
        and bare HH:MM / HH:MM as a fallback.

        Returns:
            Dict with "open_time" and "start_time" keys (values may be None).
        """
        result: dict[str, str | None] = {"open_time": None, "start_time": None}

        # Normalize full-width colon to ASCII
        text = text.replace("：", ":")

        # English: OPEN HH:MM / START HH:MM (with optional colon separator)
        eng_pattern = r"OPEN\s*[:：]?\s*(\d{1,2}:\d{2})\s*[/／\-–\s]*START\s*[:：]?\s*(\d{1,2}:\d{2})"
        match = re.search(eng_pattern, text, re.IGNORECASE)
        if match:
            result["open_time"] = match.group(1)
            result["start_time"] = match.group(2)
            return result

        # Japanese: 開場 HH:MM / 開演 HH:MM
        jp_pattern = r"開場\s*[:：]?\s*(\d{1,2}:\d{2})\s*[/／\-–\s]*開演\s*[:：]?\s*(\d{1,2}:\d{2})"
        match = re.search(jp_pattern, text)
        if match:
            result["open_time"] = match.group(1)
            result["start_time"] = match.group(2)
            return result

        # Bare fallback: HH:MM / HH:MM (two times separated by slash)
        bare_pattern = r"(\d{1,2}:\d{2})\s*[/／]\s*(\d{1,2}:\d{2})"
        match = re.search(bare_pattern, text)
        if match:
            result["open_time"] = match.group(1)
            result["start_time"] = match.group(2)
            return result

        return result

    def _extract_event_name_from_brackets(self, text: str) -> str | None:
        """Extract event name from common Japanese bracket patterns.

        Tries bracket pairs in order of specificity:
        『』, 「」, 【】, "", ''

        Returns:
            The extracted event name, or None if no bracketed text found.
        """
        bracket_pairs = [
            (r"『", r"』"),
            (r"「", r"」"),
            (r"【", r"】"),
            (r'"', r'"'),
            (r"'", r"'"),
        ]

        for open_b, close_b in bracket_pairs:
            pattern = rf"{open_b}([^{close_b}]+){close_b}"
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                if len(name) >= 2:  # noqa: PLR2004
                    return name

        return None

    def _is_valid_performer_name(self, name: str) -> bool:
        """Check if a name is likely to be a valid performer name (Japanese-focused)."""
        if not name or len(name) < 2:  # noqa: PLR2004
            return False

        # Filter out obvious non-performer content
        invalid_patterns = [
            r"^[¥￥]\d+",  # Price only
            r"^\d{1,2}:\d{2}",  # Time only
            r"^(ABOUT|HOME|SCHEDULE|ACCESS|NEWS|CONTACT|TICKET|STAFF|ACT|LIVE)$",  # Navigation (English)
            r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?$",  # Date only
            r"^(月|火|水|木|金|土|日)$",  # Day of week only
            r"^\d+$",  # Pure numbers
            r"^[-/\\()（）]+$",  # Pure punctuation
            r"^,\d+$",  # Price fragment
            r"FOOD[:：]",  # Food info
            r"入場時別途",  # Drink charge info
            r"start|open|door",  # Event timing (English)
            r"^(予約|料金|時間|開場|開演)$",  # Event info (Japanese)
            # Date patterns (e.g., "11/15(SAT", ".04(Sat)")
            r"^\d{1,2}/\d{1,2}\s*\(",  # MM/DD( format
            r"^\.\d{1,2}\s*\(",  # .DD( format
            # Phone numbers (Japanese formats)
            r"^0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}",  # 03-1234-5678, 050-1234-5678
            r"^\d{2,4}-\d{3,4}-\d{4}",  # Generic phone pattern
            # Ticket/sale text
            r"ticket\s+(on\s+)?sale",  # "Ticket on sale"
            r"(前売|当日).*(発売|販売)",  # Ticket sale Japanese
            # Contact info patterns
            r"^(月～|火～|水～|木～|金～|土～|日～)",  # Business hours start
            r"日曜.*除く",  # "Excluding Sundays"
            r"祝\s*日",  # "Holidays"
            # URLs and file paths
            r"https?://",  # URLs
            r"\.(html|php|do|aspx|jsp)(\b|$)",  # File extensions
            r"^\d+[_/]\w+",  # Path-like strings
            r"^and\s+more",  # Bare "and more" entries
            # Japanese junk text
            r"チケット.*(予約|購入|はこちら|コチラ)",  # Ticket purchase text
            # Instrument/role prefixes
            r"^(FOOD|Vocals|Guitar|Bass|Drums)[＞>：:]",
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, name, re.IGNORECASE):
                return False

        # Must contain meaningful characters (Japanese or English letters)
        if not re.search(r"[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", name):
            return False

        # Too short single characters are likely not performer names
        return len(name) != 1  # noqa: PLR2004

    def _search_for_performer_details(self, performer: Performer) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Search for additional performer details, update name formatting, and discover social media links.
        Validates performer by searching for their online presence (social media or dedicated website).
        Raises PerformerValidationError if the performer fails validation.
        """
        try:
            logger.debug(f"Starting validation search for performer: '{performer.name}'")

            # Step 1: Handle Japanese name formatting
            self._format_japanese_performer_name(performer)

            # Step 2: Search for band details online (including website discovery)
            band_info = self._search_band_details(performer.name)
            if band_info:
                self._update_performer_from_band_info(performer, band_info)
                logger.debug(f"Found band website for {performer.name}: {band_info.get('website', 'N/A')}")

            # Step 3: Search for social media links
            social_links = self._search_social_media_links(performer.name)
            if social_links:
                self._update_performer_social_links(performer, social_links)
                logger.debug(f"Found {len(social_links)} social links for {performer.name}")

            # NOTE: Do NOT save performer here - validation should not do database operations
            # The performer will be saved later in create_performance_schedule if validation passes

            # Step 4: Validate that we found legitimate online presence
            # This is the critical validation step - only validate based on actual online presence
            try:
                performer.validate_full_artist_profile()
                logger.info(f"✅ Validated artist profile: {performer.name} (found valid online presence)")
            except ValidationError:
                # If we can't find any online presence, this is likely not a real performer
                logger.warning(f"❌ Rejecting '{performer.name}': No valid online presence found")
                raise PerformerValidationError(  # noqa: B904
                    f"Cannot validate '{performer.name}' as a legitimate performer: "
                    f"No social media accounts or dedicated artist website found. "
                    f"This may be venue information, staff, or non-performer content."
                )

            logger.debug(f"Successfully validated performer: {performer.name}")

        except PerformerValidationError as e:
            # Re-raise our custom validation error
            raise PerformerValidationError from e
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to search for performer details for {performer.name}: {str(e)}")

    def _format_japanese_performer_name(self, performer: Performer) -> None:
        """Format Japanese performer names by parsing different notation patterns."""
        name = performer.name

        # Handle Japanese parenthetical notation: バンド名（読み方）
        if "（" in name and "）" in name:
            match = re.search(r"([^（]+)（([^）]+)）", name)
            if match:
                main_name = match.group(1).strip()
                reading = match.group(2).strip()

                # Main name is usually the band/artist name
                performer.name = main_name
                # Reading could be kana or romaji
                if re.search(r"[\u3040-\u309F\u30A0-\u30FF]", reading):
                    performer.name_kana = reading
                else:
                    performer.name_romaji = reading

        # Handle slash notation: 日本語名/English Name
        elif "/" in name and len(name.split("/")) == 2:  # noqa: PLR2004
            parts = [p.strip() for p in name.split("/")]
            part1, part2 = parts

            # Determine which part is Japanese vs English/Romaji
            has_jp1 = re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", part1)
            has_jp2 = re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]", part2)

            if has_jp1 and not has_jp2:
                # Part1 is Japanese, Part2 is English/Romaji
                performer.name = part1
                performer.name_romaji = part2
            elif has_jp2 and not has_jp1:
                # Part1 is English/Romaji, Part2 is Japanese
                performer.name = part2
                performer.name_romaji = part1

        # Handle middle dot notation: カタカナ・名前
        elif "・" in name:
            # This is often used in katakana names, keep as-is but might be kana
            if re.search(r"[\u30A0-\u30FF]", name):  # Contains katakana
                performer.name_kana = name

    def _search_band_details(self, band_name: str) -> dict | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Search for band details using web search.
        Returns basic information about the band/artist.
        """
        try:
            # Create search queries for Japanese bands
            search_queries = [
                f"{band_name} バンド",
                f"{band_name} アーティスト",
                f"{band_name} 音楽",
                f"{band_name} band music",
            ]

            for query in search_queries:
                try:
                    # Simple web search to find band information
                    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"

                    # Set user agent to avoid being blocked
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"  # noqa: E501
                    }

                    response = self.session.get(search_url, headers=headers, timeout=10)
                    if response.status_code == 200:  # noqa: PLR2004
                        soup = BeautifulSoup(response.text, "html.parser")  # noqa: F841

                        # Extract basic information from search results
                        band_info = {}

                        # Look for website links in search results
                        website_patterns = [
                            r'(https?://[^/]*\.(?:com|net|org|jp|co\.jp)[^"\s]*)',
                            r'(https?://[^/]*(?:bandcamp|soundcloud|spotify)\.com[^"\s]*)',
                        ]

                        for pattern in website_patterns:
                            matches = re.findall(pattern, response.text)
                            for match in matches:
                                if any(
                                    platform in match.lower() for platform in ["official", "band", "music", "artist"]
                                ):
                                    band_info["website"] = match
                                    break
                            if "website" in band_info:
                                break

                        if band_info:
                            logger.debug(f"Found band info for {band_name}: {band_info}")
                            return band_info

                except Exception as e:  # noqa: BLE001
                    logger.debug(f"Search failed for query '{query}': {str(e)}")
                    continue

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Band search failed for {band_name}: {str(e)}")

        return None

    def _search_social_media_links(self, band_name: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """
        Search for social media links for the band/artist.
        Returns a list of social media platform information.
        """
        social_links = []

        try:
            # Search for common social media platforms
            platforms = {
                "twitter": ["twitter.com", "x.com"],
                "instagram": ["instagram.com"],
                "youtube": ["youtube.com", "youtu.be"],
                "facebook": ["facebook.com"],
                "bandcamp": ["bandcamp.com"],
                "soundcloud": ["soundcloud.com"],
                "spotify": ["spotify.com"],
                "apple_music": ["music.apple.com"],
                "tiktok": ["tiktok.com"],
                "discord": ["discord.gg", "discord.com"],
                "twitch": ["twitch.tv"],
                "reddit": ["reddit.com"],
                "linkedin": ["linkedin.com"],
                "vimeo": ["vimeo.com"],
                "github": ["github.com"],
                "patreon": ["patreon.com"],
                "mastodon": ["mastodon.social", "mastodon.online"],
            }

            search_query = f"{band_name} social media twitter instagram youtube"
            search_url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"  # noqa: E501
            }

            response = self.session.get(search_url, headers=headers, timeout=10)
            if response.status_code == 200:  # noqa: PLR2004
                text = response.text

                # Extract social media URLs
                url_pattern = r'https?://[^"\s<>]+'
                urls = re.findall(url_pattern, text)

                for url in urls:
                    for platform, domains in platforms.items():
                        for domain in domains:
                            if domain in url.lower():
                                # Extract platform ID from URL
                                platform_id = self._extract_platform_id(url, platform)
                                if platform_id:
                                    social_links.append({"platform": platform, "platform_id": platform_id, "url": url})
                                break

                        # Limit to avoid too many duplicate results
                        if len(social_links) >= 5:  # noqa: PLR2004
                            break

                    if len(social_links) >= 5:  # noqa: PLR2004
                        break

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Social media search failed for {band_name}: {str(e)}")

        return social_links[:5]  # Limit to 5 social links

    def _extract_platform_id(self, url: str, platform: str) -> str | None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Extract platform-specific ID from social media URL."""
        try:
            if platform == "twitter":
                match = re.search(r"(?:twitter\.com|x\.com)/([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "instagram":
                match = re.search(r"instagram\.com/([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "youtube":
                match = re.search(r"youtube\.com/(?:c/|channel/|user/)?([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "facebook":
                match = re.search(r"facebook\.com/([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform in ["bandcamp", "soundcloud", "spotify"]:
                match = re.search(rf"{platform}\.com/([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "tiktok":
                match = re.search(r"tiktok\.com/@?([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "discord":
                match = re.search(r"discord\.(?:gg|com)/([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "twitch":
                match = re.search(r"twitch\.tv/([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "reddit":
                match = re.search(r"reddit\.com/(?:r/|u/|user/)?([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform in ["linkedin", "vimeo", "github", "patreon"]:
                match = re.search(rf"{platform}\.com/([^/?\s]+)", url)
                return match.group(1) if match else None
            if platform == "mastodon":
                match = re.search(r"mastodon\.(?:social|online)/(@?[^/?\s]+)", url)
                return match.group(1) if match else None

        except Exception:  # noqa: BLE001, S110
            pass

        return None

    def _update_performer_from_band_info(self, performer: Performer, band_info: dict) -> None:
        """Update performer with information found from band search."""
        try:
            if "website" in band_info and not performer.website:
                performer.website = band_info["website"]
                logger.debug(f"Added website for {performer.name}: {band_info['website']}")

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Failed to update performer from band info: {str(e)}")

    def _update_performer_social_links(self, performer: Performer, social_links: list[dict]) -> None:
        """Update performer with discovered social media links.

        Note: YouTube links are skipped here as they are populated more accurately
        from youtube_search.search_and_create_performer_songs() which extracts
        the channel ID directly from YouTube's data.
        """
        try:
            for link_info in social_links:
                # Skip YouTube links - these are handled by youtube_search module
                if link_info["platform"] == "youtube":
                    continue

                _, created = PerformerSocialLink.objects.get_or_create(
                    performer=performer,
                    platform=link_info["platform"],
                    defaults={
                        "platform_id": link_info["platform_id"],
                        "url": link_info["url"],
                    },
                )
                if created:
                    logger.debug(f"Added {link_info['platform']} link for {performer.name}: {link_info['url']}")

        except Exception as e:  # noqa: BLE001
            logger.debug(f"Failed to update social links: {str(e)}")

    def _extract_ticket_info(  # noqa: C901, PLR0912, PLR0915, PLR0911
        self, html_content: str, context: str = ""
    ) -> PerformanceScheduleTicketPurchaseInfo | None:
        """
        Generic helper method to extract ticket information from HTML content.
        Returns a PerformanceScheduleTicketPurchaseInfo object (not saved to DB yet).
        """
        soup = self.create_soup(html_content)
        text = soup.get_text() + " " + context

        # Initialize a ticket info object (not saved to DB yet)
        ticket_info = PerformanceScheduleTicketPurchaseInfo()
        has_ticket_data = False

        # Extract email addresses
        email_patterns = [
            r"(?:チケット|ticket|予約|reservation)[：:\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        ]

        for pattern in email_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                email = match.group(1) if len(match.groups()) > 0 else match.group(0)
                # Filter out common non-ticket emails
                if not any(domain in email.lower() for domain in ["facebook", "twitter", "instagram", "youtube"]):
                    ticket_info.ticket_contact_email = email
                    has_ticket_data = True
                    break

        # Extract phone numbers
        phone_patterns = [
            r"(?:チケット|ticket|予約|reservation)[：:\s]*(\d{2,4}[-‐]\d{3,4}[-‐]\d{3,4})",
            r"(?:連絡|contact|問合|お問い合わせ)[：:\s]*(\d{2,4}[-‐]\d{3,4}[-‐]\d{3,4})",
        ]

        for pattern in phone_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                ticket_info.ticket_contact_phone = match.group(1)
                has_ticket_data = True
                break

        # Extract ticket URLs
        url_patterns = [
            r"(?:チケット|ticket|予約|reservation)[：:\s]*(?:URL[：:\s]*)?(https?://[^\s\)]+)",
            r"(https?://[^\s]*(?:ticket|peatix|eventbrite|eplus|cnplayguide)[^\s]*)",
        ]

        for pattern in url_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                url = match.group(1) if len(match.groups()) > 0 else match.group(0)
                # Clean up URL
                url = url.rstrip(".,;)")
                ticket_info.ticket_url = url
                has_ticket_data = True
                break

        # Extract ticket prices
        price_patterns = [
            r"(?:チケット|ticket|料金|price)[：:\s]*[¥￥]?\s*(\d{1,2},?\d{3})[円¥]?",
            r"(?:前売|advance)[：:\s]*[¥￥]?\s*(\d{1,2},?\d{3})[円¥]?",
            r"(?:当日|door)[：:\s]*[¥￥]?\s*(\d{1,2},?\d{3})[円¥]?",
        ]

        for pattern in price_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(",", "")
                try:
                    price = float(price_str)
                    # Reasonable price range for live house tickets
                    if 500 <= price <= 20000:  # noqa: PLR2004
                        ticket_info.ticket_price = price
                        has_ticket_data = True
                        break
                except ValueError:
                    continue

        # Extract sales dates
        date_patterns = [
            r"(?:発売|sale|販売)[：:\s]*(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?",
            r"(?:受付|reception)[：:\s]*(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?",
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    year = int(match.group(1))
                    month = int(match.group(2))
                    day = int(match.group(3))

                    if 2024 <= year <= 2026 and 1 <= month <= 12 and 1 <= day <= 31:  # noqa: PLR2004
                        date_obj = date(year, month, day)
                        ticket_info.ticket_sales_start_date = timezone.datetime.combine(
                            date_obj, timezone.datetime.min.time()
                        ).replace(tzinfo=timezone.get_current_timezone())
                        has_ticket_data = True
                        break
                except (ValueError, IndexError):
                    continue

        return ticket_info if has_ticket_data else None

    def _create_or_update_ticket_info(
        self, performance: PerformanceSchedule, ticket_info: PerformanceScheduleTicketPurchaseInfo
    ) -> None:
        """Create or update PerformanceScheduleTicketPurchaseInfo for a performance."""
        try:
            # Prepare data for update_or_create
            defaults = {}

            if ticket_info.ticket_contact_email:
                defaults["ticket_contact_email"] = ticket_info.ticket_contact_email
            if ticket_info.ticket_contact_phone:
                defaults["ticket_contact_phone"] = ticket_info.ticket_contact_phone
            if ticket_info.ticket_url:
                defaults["ticket_url"] = ticket_info.ticket_url
            if ticket_info.ticket_price:
                defaults["ticket_price"] = ticket_info.ticket_price
            if ticket_info.ticket_sales_start_date:
                defaults["ticket_sales_start_date"] = ticket_info.ticket_sales_start_date
            if ticket_info.ticket_sales_end_date:
                defaults["ticket_sales_end_date"] = ticket_info.ticket_sales_end_date

            if not defaults:
                logger.debug(f"No ticket info to save for performance {performance}")
                return

            # Create or update ticket purchase info
            saved_ticket_info, created = PerformanceScheduleTicketPurchaseInfo.objects.update_or_create(
                performance=performance, defaults=defaults
            )

            action = "Created" if created else "Updated"
            logger.debug(f"{action} ticket info for performance {performance}: {list(defaults.keys())}")

        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to create/update ticket info for {performance}: {str(e)}")
