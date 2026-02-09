# malcom/houses/management/commands/list_tokyo_livehouses.py
import json
import logging
from pathlib import Path
from urllib.parse import urljoin

import requests
from django.core.management.base import BaseCommand

from ...crawlers.crawler import CrawlerRegistry
from ...models import LiveHouse

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Lists live house venues in Tokyo with capacity <= 350 and their schedule URLs."

    def handle(self, *args, **options):  # noqa: ANN002, ANN003
        self.stdout.write("Searching for Tokyo live houses with capacity <= 350...")

        output_data = []

        try:
            # Filter LiveHouse instances by capacity and address (assuming "Tokyo" in address indicates Tokyo area)
            tokyo_livehouses = LiveHouse.objects.filter(capacity__lte=350, address__icontains="Tokyo").select_related(
                "website"
            )  # Select related website to avoid N+1 queries

            if not tokyo_livehouses.exists():
                self.stdout.write(self.style.WARNING("No live houses found matching the criteria."))
                return

            self.stdout.write(f"Found {tokyo_livehouses.count()} potential live houses.")

            for live_house in tokyo_livehouses:
                self.stdout.write(f"Processing {live_house.name}...")
                main_url = live_house.website.url
                schedule_url = None

                # Attempt to get the schedule URL dynamically using the appropriate crawler
                crawler_class_name = live_house.website.crawler_class
                if not crawler_class_name:
                    # If crawler_class is not set, use the base crawler but this might not work for all sites
                    crawler_class_name = "LiveHouseWebsiteCrawler"
                    # If the base class does not define how to extract schedule for this specific website, it will fail
                    self.stdout.write(
                        self.style.WARNING(
                            f"  No specific crawler for {live_house.name}, trying generic. This might fail."
                        )
                    )

                crawler_class = CrawlerRegistry.get_crawler(crawler_class_name)

                if crawler_class:
                    try:
                        # Instantiate the crawler and use its methods to find the schedule link
                        # We don't want to run the full crawler, just use its helper methods
                        # Instantiate without triggering the full run method which updates DB state
                        crawler = crawler_class(live_house.website)

                        # Fetch the main page content
                        main_page_content = crawler.fetch_page(main_url)

                        # Find the schedule link
                        found_schedule_link = crawler.find_schedule_link(main_page_content)
                        if found_schedule_link:
                            # The found_schedule_link might be relative, so use urljoin
                            schedule_url = urljoin(main_url, found_schedule_link)
                            self.stdout.write(self.style.SUCCESS(f"  Found schedule URL: {schedule_url}"))
                        else:
                            self.stdout.write(self.style.WARNING("  Could not find schedule URL."))

                    except requests.exceptions.RequestException as req_exc:
                        self.stdout.write(
                            self.style.ERROR(f"  Network error fetching {main_url} for {live_house.name}: {req_exc}")
                        )
                    except Exception as e:  # noqa: BLE001
                        self.stdout.write(self.style.ERROR(f"  Error finding schedule URL for {live_house.name}: {e}"))
                else:
                    self.stdout.write(
                        self.style.ERROR(f"  No crawler class found for '{crawler_class_name}' for {live_house.name}.")
                    )

                # Append data to output
                output_data.append(
                    {
                        "name": live_house.name,
                        "url": main_url,
                        "schedule_url": schedule_url if schedule_url else "N/A",  # Indicate if not found
                    }
                )

            # Write to JSON file
            output_filename = "LIVEHOUSE_SEARCH_202602.json"
            with Path(output_filename).open("w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)

            self.stdout.write(
                self.style.SUCCESS(f"Successfully listed {len(output_data)} live houses to {output_filename}")
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An unexpected error occurred: {e}"))
            logger.exception("Error in list_tokyo_livehouses command")
