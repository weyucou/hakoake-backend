from argparse import ArgumentParser
from datetime import date, datetime

from commons.functions import get_month_end
from django.core.management.base import BaseCommand
from houses.models import PerformanceSchedule


class Command(BaseCommand):
    help = "List all performers scheduled for a given month with venue, date, and cost information"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--month",
            type=str,
            help="Target month in YYYY-MM format. Defaults to current month.",
        )
        parser.add_argument(
            "--upcoming-only",
            action="store_true",
            help="Only show performances from today onwards (only applies to current month)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        """
        List all performers scheduled for a given month.

        Outputs: Performer ID, Performer Name, Venue Name, Performance Date, Presale Price, Door Price
        """
        month_str = options.get("month")
        upcoming_only = options.get("upcoming_only", False)

        # Determine target month
        if month_str:
            try:
                target_date = datetime.strptime(month_str, "%Y-%m").date()  # noqa: DTZ007
            except ValueError:
                self.stdout.write(self.style.ERROR(f"Invalid month format: {month_str}. Use YYYY-MM."))
                return
        else:
            today = date.today()  # noqa: DTZ011
            target_date = date(today.year, today.month, 1)

        # Calculate month range
        year = target_date.year
        month = target_date.month
        month_start = date(year, month, 1)

        month_end = get_month_end(month_start)

        # Get all performances in the target month
        performances = PerformanceSchedule.objects.filter(
            performance_date__gte=month_start,
            performance_date__lt=month_end,
        ).select_related("live_house")

        # Apply upcoming filter if requested
        if upcoming_only:
            today = date.today()  # noqa: DTZ011
            performances = performances.filter(performance_date__gte=today)

        performances = performances.order_by("performance_date", "start_time")

        if not performances.exists():
            self.stdout.write(self.style.WARNING(f"No performances found for {target_date.strftime('%Y-%m')}."))
            return

        # Print header
        month_display = target_date.strftime("%B %Y")
        self.stdout.write(f"\nPerformers scheduled for {month_display}")
        if upcoming_only:
            self.stdout.write(" (upcoming only)")
        self.stdout.write("\n")

        self.stdout.write(
            f"{'Performer ID':<15} {'Performer Name':<30} {'Venue':<30} "
            f"{'Performance Date':<18} {'Presale':<10} {'Door':<10}"
        )
        self.stdout.write("-" * 125)

        # Track unique performers and total performances
        unique_performers = set()
        performance_count = 0

        for schedule in performances:
            performers = schedule.performers.all()

            if performers.exists():
                for performer in performers:
                    unique_performers.add(performer.id)

                    presale = f"¥{schedule.presale_price:,.0f}" if schedule.presale_price else "-"
                    door = f"¥{schedule.door_price:,.0f}" if schedule.door_price else "-"

                    self.stdout.write(
                        f"{performer.id:<15} {performer.name[:28]:<30} "
                        f"{schedule.live_house.name[:28]:<30} {str(schedule.performance_date):<18} "
                        f"{presale:<10} {door:<10}"
                    )
                    performance_count += 1
            else:
                # Show performance even without performers (shouldn't normally happen)
                self.stdout.write(
                    f"{'(no performers)':<15} {'(no performers)':<30} "
                    f"{schedule.live_house.name[:28]:<30} {str(schedule.performance_date):<18} "
                    f"{'-':<10} {'-':<10}"
                )

        # Print summary
        self.stdout.write("-" * 125)
        self.stdout.write(f"Total unique performers: {len(unique_performers)}")
        self.stdout.write(f"Total performances listed: {performance_count}\n")
