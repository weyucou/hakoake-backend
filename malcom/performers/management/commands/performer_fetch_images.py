"""Management command to fetch images for a specific performer by ID."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from performers.image_fetcher import fetch_and_update_performer_images
from performers.models import Performer


class Command(BaseCommand):
    """Fetch and update images for a performer by ID."""

    help = "Fetch and update performer images from TheAudioDB (with MusicBrainz fallback)"

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        """Add command arguments."""
        parser.add_argument(
            "performer_id",
            type=int,
            help="ID of the performer to fetch images for",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, ARG002
        """Execute the command."""
        performer_id = options["performer_id"]

        try:
            performer = Performer.objects.get(id=performer_id)
        except Performer.DoesNotExist:
            raise CommandError(f"Performer with ID {performer_id} not found")  # noqa: B904

        self.stdout.write(f"Fetching images for: {performer.name} (ID: {performer.id})")

        with transaction.atomic():
            results = fetch_and_update_performer_images(performer)

        fetched = [image_type for image_type, success in results.items() if success]
        if fetched:
            self.stdout.write(self.style.SUCCESS(f"Fetched: {', '.join(fetched)}"))
        else:
            self.stdout.write(self.style.WARNING("No images found"))
