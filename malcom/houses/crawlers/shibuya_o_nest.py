import logging
import re

from django.utils import timezone

from ..models import LiveHouse
from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)

SHIBUYA_O_NEST_BASE_URL = "https://shibuya-o.com/nest"
SHIBUYA_O_NEST_API_URL = "https://shibuya-o.com/wp-json/wp/v2/nest-schedule"


@CrawlerRegistry.register("ShibuyaONestCrawler")
class ShibuyaONestCrawler(LiveHouseWebsiteCrawler):
    """
    Crawler for Shibuya O-Nest (shibuya-o.com/nest/).

    The schedule list page is JavaScript-rendered. Events are fetched via the
    WordPress REST API (nest-schedule custom post type). Each event's detail
    page is server-rendered HTML and parsed for date, time, and performers.

    Detail page structure:
    - Date:       .p-schedule-detail__date-item  e.g. "05 / 14"
    - Day of week:.p-schedule-detail__date-week  e.g. "THU"
    - OPEN/START: .p-schedule-detail__dt / .p-schedule-detail__dd
    - Performers: .c-wp-editor <p> with "出演：A / B / C"
    - Image:      img.wp-post-image
    """

    def extract_live_house_info(self, html_content: str) -> dict[str, str]:
        return {
            "name": "Shibuya O-Nest",
            "name_kana": "シブヤ オーネスト",
            "name_romaji": "Shibuya O-Nest",
            "address": "",
            "phone_number": "",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        return SHIBUYA_O_NEST_API_URL

    def process_performance_schedules(self, schedule_url: str, live_house: LiveHouse) -> None:
        schedules = self._fetch_all_schedules_via_api()
        created_count = 0
        total_performers: set[str] = set()

        for schedule_data in schedules:
            try:
                performance = self.create_performance_schedule(live_house, schedule_data)
                created_count += 1
                for performer in performance.performers.all():
                    total_performers.add(performer.name)
            except Exception:  # noqa: BLE001
                logger.exception(f"Failed to create schedule for {schedule_data}")

        logger.info(f"Created {created_count} performance schedules for {live_house.name}")
        if total_performers:
            logger.info(f"  Unique performers: {len(total_performers)}")

    def extract_performance_schedules(self, html_content: str) -> list[dict]:
        # Not called — process_performance_schedules is overridden to use the REST API.
        return []

    def _fetch_all_schedules_via_api(self) -> list[dict]:
        schedules = []
        page = 1
        while True:
            url = f"{SHIBUYA_O_NEST_API_URL}?per_page=100&page={page}"
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code in (400, 404):
                break
            response.raise_for_status()
            posts = response.json()
            if not posts:
                break
            for post in posts:
                schedule = self._parse_detail_page(post["link"])
                if schedule:
                    schedules.append(schedule)
            total_pages = int(response.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1
        logger.info(f"Fetched {len(schedules)} schedules from O-Nest REST API")
        return schedules

    def _parse_detail_page(self, url: str) -> dict | None:
        try:
            html = self.fetch_page(url)
            return self._parse_detail_html(html, url)
        except Exception:  # noqa: BLE001
            logger.warning(f"Failed to fetch/parse O-Nest detail page: {url}")
            return None

    def _parse_detail_html(self, html: str, source_url: str) -> dict | None:
        soup = self.create_soup(html)
        date_str = self._extract_date_str(soup, source_url)
        if not date_str:
            return None

        open_time, start_time = self._extract_open_start_from_dl(soup)
        event_name = self._extract_event_name(soup)
        performers = self._extract_performers_from_content(soup, event_name)
        event_image_url = self._extract_event_image_url(soup)
        content_div = soup.find("div", class_="c-wp-editor")
        context_parts = [event_name]
        if content_div:
            context_parts.append(content_div.get_text(separator=" ", strip=True))

        schedule: dict = {
            "date": date_str,
            "open_time": open_time or "18:30",
            "start_time": start_time or "19:00",
            "performers": performers,
            "performance_name": event_name,
            "source_url": source_url,
            "context": "\n".join(context_parts),
        }
        if event_image_url:
            schedule["event_image_url"] = event_image_url
        return schedule

    def _extract_date_str(self, soup: object, source_url: str) -> str | None:
        date_item = soup.find("span", class_="p-schedule-detail__date-item")  # type: ignore[union-attr]
        if not date_item:
            logger.debug(f"No date element found on: {source_url}")
            return None
        date_text = date_item.get_text(strip=True)
        date_match = re.match(r"(\d{1,2})\s*/\s*(\d{1,2})", date_text)
        if not date_match:
            logger.debug(f"Unparsable date '{date_text}' on: {source_url}")
            return None
        month = int(date_match.group(1))
        day = int(date_match.group(2))
        today = timezone.localdate()
        year = today.year
        if today.month >= 11 and month <= 2:  # noqa: PLR2004
            year += 1
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _extract_open_start_from_dl(self, soup: object) -> tuple[str | None, str | None]:
        open_time: str | None = None
        start_time: str | None = None
        for dl in soup.find_all("div", class_="p-schedule-detail__dl"):  # type: ignore[union-attr]
            dt_el = dl.find("div", class_="p-schedule-detail__dt")
            dd_el = dl.find("div", class_="p-schedule-detail__dd")
            if not (dt_el and dd_el):
                continue
            dt_text = dt_el.get_text(strip=True)
            dd_text = dd_el.get_text(strip=True)
            if dt_text == "OPEN":
                open_time = dd_text
            elif dt_text == "START":
                start_time = dd_text
        return open_time, start_time

    def _extract_event_name(self, soup: object) -> str:
        title_span = soup.find("span", class_="p-schedule-detail__title-main")  # type: ignore[union-attr]
        return title_span.get_text(strip=True) if title_span else ""

    def _extract_performers_from_content(self, soup: object, event_name: str) -> list[str]:
        content_div = soup.find("div", class_="c-wp-editor")  # type: ignore[union-attr]
        performers: list[str] = []
        if content_div:
            content_text = content_div.get_text(separator=" ", strip=True)
            content_text = re.sub(r"^出演[：:]\s*", "", content_text)
            for raw_name in re.split(r"\s*/\s*|／", content_text):
                cleaned = self._clean_performer_name(raw_name.strip())
                if cleaned and self._is_valid_performer_name(cleaned):
                    performers.append(cleaned)
        if not performers and event_name:
            performers = [event_name]
        return performers

    def _extract_event_image_url(self, soup: object) -> str | None:
        img = soup.find("img", class_="wp-post-image")  # type: ignore[union-attr]
        return img["src"] if img and img.get("src") else None
