from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from performers.models import Performer, PerformerSocialLink


class Command(BaseCommand):
    help = "Set verified_datetime to current datetime for a PerformerSocialLink"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--performer-id",
            type=int,
            required=True,
            help="ID of the Performer",
        )
        parser.add_argument(
            "--platform",
            type=str,
            required=True,
            help="Platform name (e.g., youtube, twitter, instagram)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        """Set verified_datetime to current datetime."""
        performer_id = options["performer_id"]
        platform = options["platform"]

        try:
            performer = Performer.objects.get(id=performer_id)
        except Performer.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Performer with id={performer_id} not found"))
            return

        try:
            link = PerformerSocialLink.objects.get(performer=performer, platform=platform)
        except PerformerSocialLink.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    f"PerformerSocialLink for performer '{performer.name}' with platform '{platform}' not found"
                )
            )
            return

        now = timezone.now()
        link.verified_datetime = now
        link.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Verified PerformerSocialLink for '{performer.name}' ({platform}):\n"
                f"  URL: {link.url}\n"
                f"  Verified at: {now.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        )
