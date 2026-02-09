"""Management command to fetch images for performers."""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from performers.image_fetcher import fetch_and_update_performer_images
from performers.models import Performer


class Command(BaseCommand):
    """Fetch and update performer images from TheAudioDB."""

    help = "Fetch and update performer images from TheAudioDB"

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        """Add command arguments."""
        parser.add_argument(
            "--performer-id",
            type=int,
            help="Fetch images for a specific performer by ID",
        )
        parser.add_argument(
            "--performer-name",
            type=str,
            help="Fetch images for a specific performer by name",
        )
        parser.add_argument(
            "--missing-only",
            action="store_true",
            help="Only fetch images for performers missing one or both images",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-fetch images even if they already exist",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, ARG002, C901, PLR0912, PLR0915
        """Execute the command."""
        performer_id = options.get("performer_id")
        performer_name = options.get("performer_name")
        missing_only = options.get("missing_only", False)
        force = options.get("force", False)

        # Build queryset
        if performer_id:
            performers = Performer.objects.filter(id=performer_id)
            if not performers.exists():
                self.stdout.write(self.style.ERROR(f"Performer with ID {performer_id} not found"))
                return
        elif performer_name:
            performers = Performer.objects.filter(name__icontains=performer_name)
            if not performers.exists():
                self.stdout.write(self.style.ERROR(f"No performers found matching '{performer_name}'"))
                return
        else:
            performers = Performer.objects.all()

        # Filter for missing images if requested
        if missing_only and not force:
            performers = performers.filter(
                Q(performer_image="")
                | Q(performer_image__isnull=True)
                | Q(logo_image="")
                | Q(logo_image__isnull=True)
                | Q(fanart_image="")
                | Q(fanart_image__isnull=True)
                | Q(banner_image="")
                | Q(banner_image__isnull=True)
            )

        total_count = performers.count()
        if total_count == 0:
            self.stdout.write(self.style.WARNING("No performers to process"))
            return

        self.stdout.write(f"Processing {total_count} performer(s)...")

        success_count = 0
        partial_count = 0
        failure_count = 0

        for performer in performers:
            self.stdout.write(f"\nProcessing: {performer.name} (ID: {performer.id})")

            # Clear existing images if force is enabled
            if force:
                for field_name in ("performer_image", "logo_image", "fanart_image", "banner_image"):
                    field = getattr(performer, field_name)
                    if field:
                        field.delete(save=False)

            # Fetch and update images
            with transaction.atomic():
                results = fetch_and_update_performer_images(performer)

                # Reload from database to get updated image fields
                performer.refresh_from_db()

                fetched_types = [k for k, v in results.items() if v]
                if len(fetched_types) == len(results):
                    self.stdout.write(self.style.SUCCESS("  ✓ Successfully fetched all images"))
                    success_count += 1
                elif fetched_types:
                    self.stdout.write(self.style.WARNING(f"  ⚠ Partially successful: {', '.join(fetched_types)}"))
                    partial_count += 1
                else:
                    self.stdout.write(self.style.ERROR("  ✗ No images found"))
                    failure_count += 1

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("\nSummary:"))
        self.stdout.write(f"  Total processed: {total_count}")
        self.stdout.write(self.style.SUCCESS(f"  Full success: {success_count}"))
        if partial_count > 0:
            self.stdout.write(self.style.WARNING(f"  Partial success: {partial_count}"))
        if failure_count > 0:
            self.stdout.write(self.style.ERROR(f"  Failed: {failure_count}"))
