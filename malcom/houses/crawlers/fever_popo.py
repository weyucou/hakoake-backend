import logging
import re

from django.utils import timezone

from .crawler import CrawlerRegistry, LiveHouseWebsiteCrawler

logger = logging.getLogger(__name__)

FEVER_POPO_BASE_URL = "https://www.fever-popo.com"


@CrawlerRegistry.register("FeverPopoCrawler")
class FeverPopoCrawler(LiveHouseWebsiteCrawler):
    """
    Crawler for 新代田FEVER (LIVE HOUSE FEVER) website.

    Schedule page structure (as of 2026-05):
    - <h2 class="eventtitle">YY.MM.DD (Day) Event Title</h2>
    - <p><img src="...flyer..."></p>
    - <h3><p>Performer1<br>Performer2</p></h3>
    - <div>OPEN HH:MM / START HH:MM</div>
    - <div><p>ADV ¥XXXX / DOOR ¥XXXX</p></div>
    """

    def extract_live_house_info(self, html_content: str) -> dict[str, str]:
        return {
            "name": "新代田FEVER",
            "name_kana": "シンダイタフィーバー",
            "name_romaji": "Shindaita FEVER",
            "address": "東京都世田谷区羽根木1-1-14 新代田ビル1F",
            "phone_number": "03-6304-7899",
            "capacity": 0,
            "opened_date": None,
        }

    def find_schedule_link(self, html_content: str) -> str | None:
        current_date = timezone.localdate()
        return f"{FEVER_POPO_BASE_URL}/schedule/{current_date.year}/{current_date.month:02d}/"

    def extract_performance_schedules(self, html_content: str) -> list[dict]:  # noqa: C901, PLR0912, PLR0915
        """
        Extract performance schedules from FEVER schedule page.

        Current structure (as of 2026-05):
        - <h2 class="eventtitle">YY.MM.DD (Day) Event Title</h2>  [date + event name]
        - <p><img ...></p>                                          [flyer image]
        - <h3><p>Performer1<br>Performer2</p></h3>                 [performers]
        - <div>OPEN HH:MM / START HH:MM</div>                     [times]
        - <div><p>ADV ¥XXXX / DOOR ¥XXXX</p></div>                [ticket info]
        """
        soup = self.create_soup(html_content)
        schedules = []

        h2_elements = soup.find_all("h2", class_="eventtitle")
        logger.debug(f"Found {len(h2_elements)} H2 eventtitle headers on FEVER schedule page")

        for h2 in h2_elements:
            h2_text = h2.get_text(separator=" ", strip=True)

            # Date format: YY.MM.DD (Day) Event Name  e.g. "26.05.01 (Fri) Event Title"
            date_match = re.match(r"(\d{2})\.(\d{2})\.(\d{2})\s*\([^)]+\)\s*(.*)", h2_text)
            if not date_match:
                continue

            yy = int(date_match.group(1))
            month = int(date_match.group(2))
            day = int(date_match.group(3))
            event_name = date_match.group(4).strip()

            year = 2000 + yy
            date_str = f"{year:04d}-{month:02d}-{day:02d}"

            performers: list[str] = []
            open_time = "18:30"
            start_time = "19:00"
            event_image_url: str | None = None
            context_parts = [h2_text]

            # Walk into the asset-content block that follows this header
            asset_header = h2.find_parent(class_="asset-header")
            if asset_header:
                asset_content = asset_header.find_next_sibling(class_="asset-content")
            else:
                asset_content = None

            search_root = asset_content if asset_content else h2.parent

            # Flyer image
            img = search_root.find("img", src=True)
            if img:
                event_image_url = img["src"]

            # Performers in <h3><p>...</p></h3>
            for h3 in search_root.find_all("h3"):
                performer_text = h3.get_text(separator="\n", strip=True)
                context_parts.append(performer_text)
                for line in performer_text.split("\n"):
                    cleaned = self._clean_performer_name(line.strip())
                    if cleaned and self._is_valid_performer_name(cleaned):
                        performers.append(cleaned)

            # Times in <div>OPEN HH:MM / START HH:MM</div>
            for div in search_root.find_all("div"):
                div_text = div.get_text(strip=True)
                time_match = re.search(r"OPEN\s*(\d{1,2}:\d{2})\s*/\s*START\s*(\d{1,2}:\d{2})", div_text, re.IGNORECASE)
                if time_match:
                    open_time = time_match.group(1)
                    start_time = time_match.group(2)
                    context_parts.append(div_text)
                    break

            if not performers and not event_name:
                continue

            schedule: dict = {
                "date": date_str,
                "open_time": open_time,
                "start_time": start_time,
                "performers": performers if performers else [event_name],
                "performance_name": event_name,
                "context": "\n".join(context_parts),
            }
            if event_image_url:
                schedule["event_image_url"] = event_image_url
            schedules.append(schedule)

        logger.info(f"Extracted {len(schedules)} schedules from FEVER website")
        return schedules

    def find_next_month_link(self, html_content: str) -> str | None:
        current_date = timezone.localdate()
        next_month = (current_date.month % 12) + 1
        next_year = current_date.year if next_month > current_date.month else current_date.year + 1
        return f"{FEVER_POPO_BASE_URL}/schedule/{next_year}/{next_month:02d}/"
