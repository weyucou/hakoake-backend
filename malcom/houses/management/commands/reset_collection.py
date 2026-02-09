from datetime import datetime

from django.core.management import BaseCommand
from django.db import transaction
from houses.definitions import CrawlerCollectionState
from houses.models import LiveHouse, PerformanceSchedule


class Command(BaseCommand):
    help = "Reset collection data for a specific venue from a target date onwards"

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        """Add command-line arguments."""
        parser.add_argument(
            "--venue-id",
            type=int,
            required=True,
            help="Required: The ID of the venue to reset collection data for",
        )
        parser.add_argument(
            "--target-date",
            type=str,
            required=True,
            help="Required: Target date to reset from (format: YYYY-MM-DD)",
        )

    def handle(self, *args, **options) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
        """Run the collection reset process."""
        venue_id = options["venue_id"]
        target_date_str = options["target_date"]

        # Parse target date
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError:
            self.stderr.write(self.style.ERROR(f"Invalid date format: {target_date_str}. Expected format: YYYY-MM-DD"))
            return

        # Get venue
        try:
            venue = LiveHouse.objects.get(id=venue_id)
        except LiveHouse.DoesNotExist:  # noqa: DJ012
            self.stderr.write(self.style.ERROR(f"Venue with ID {venue_id} does not exist"))
            return

        self.stdout.write(f"\nResetting collection data for: {venue.name} (ID: {venue_id})")
        self.stdout.write(f"Target date: {target_date}\n")

        # Get schedules to delete
        schedules_to_delete = PerformanceSchedule.objects.filter(live_house=venue, performance_date__gte=target_date)

        # Count and show what will be deleted
        count = schedules_to_delete.count()

        if count == 0:
            self.stdout.write(self.style.WARNING("No schedules found to delete"))
            return

        # Show date range
        earliest = schedules_to_delete.order_by("performance_date").first()
        latest = schedules_to_delete.order_by("-performance_date").first()

        self.stdout.write(f"Found {count} schedules to delete:")
        self.stdout.write(f"  Date range: {earliest.performance_date} to {latest.performance_date}")

        # Count unique performers
        unique_performers = set()
        for schedule in schedules_to_delete:
            for performer in schedule.performers.all():
                unique_performers.add(performer.name)

        self.stdout.write(f"  Unique performers affected: {len(unique_performers)}\n")

        # Confirm deletion
        confirm = input("Are you sure you want to delete these schedules? (yes/no): ")
        if confirm.lower() != "yes":
            self.stdout.write(self.style.WARNING("Operation cancelled"))
            return

        # Perform deletion and reset in a transaction
        with transaction.atomic():
            # Delete schedules
            deleted_count, _ = schedules_to_delete.delete()

            # Reset venue collection state
            venue.last_collected_datetime = None
            venue.last_collection_state = CrawlerCollectionState.PENDING
            venue.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Successfully deleted {deleted_count} schedules for {venue.name} from {target_date} onwards"
                )
            )
            self.stdout.write(self.style.SUCCESS(f"✓ Reset last_collected_datetime for {venue.name}"))
