"""Management command to clean 'BAND:' prefix from performer names."""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from performers.models import Performer


class Command(BaseCommand):
    help = "Remove 'BAND:' prefix from all performer name fields"

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )

    def handle(self, *args, **options):  # noqa: ANN002, ANN003, PLR0912
        """Remove 'BAND:' prefix from all performer names."""
        dry_run = options.get("dry_run", False)

        # Find all performers with "BAND:" prefix in any name field
        performers_to_update = (
            Performer.objects.filter(name__istartswith="BAND:")
            | Performer.objects.filter(name_kana__istartswith="BAND:")
            | Performer.objects.filter(name_romaji__istartswith="BAND:")
        )

        performers_to_update = performers_to_update.distinct()

        if not performers_to_update.exists():
            self.stdout.write(self.style.SUCCESS("No performers found with 'BAND:' prefix"))
            return

        self.stdout.write(f"\nFound {performers_to_update.count()} performer(s) with 'BAND:' prefix:\n")

        updated_count = 0
        for performer in performers_to_update:
            old_name = performer.name
            old_name_kana = performer.name_kana
            old_name_romaji = performer.name_romaji

            # Clean the names
            new_name = re.sub(r"^BAND:\s*", "", performer.name, flags=re.IGNORECASE)
            new_name_kana = re.sub(r"^BAND:\s*", "", performer.name_kana, flags=re.IGNORECASE)
            new_name_romaji = re.sub(r"^BAND:\s*", "", performer.name_romaji, flags=re.IGNORECASE)

            # Check if any changes were made
            changes = []
            if old_name != new_name:
                changes.append(f"name: '{old_name}' → '{new_name}'")
            if old_name_kana != new_name_kana:
                changes.append(f"name_kana: '{old_name_kana}' → '{new_name_kana}'")
            if old_name_romaji != new_name_romaji:
                changes.append(f"name_romaji: '{old_name_romaji}' → '{new_name_romaji}'")

            if changes:
                self.stdout.write(f"\nPerformer ID {performer.id}:")
                for change in changes:
                    self.stdout.write(f"  {change}")

                if not dry_run:
                    # Check if there's already a performer with the cleaned name_romaji
                    existing_performer = (
                        Performer.objects.filter(name_romaji=new_name_romaji).exclude(id=performer.id).first()
                    )

                    if existing_performer:
                        # Merge with existing performer
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Found duplicate performer ID {existing_performer.id} "
                                f"with name_romaji='{new_name_romaji}'"
                            )
                        )
                        self.stdout.write(f"  Merging ID {performer.id} into ID {existing_performer.id}...")

                        with transaction.atomic():
                            # Move all performance schedules to the existing performer
                            for schedule in performer.performance_schedules.all():
                                schedule.performers.add(existing_performer)
                                schedule.performers.remove(performer)

                            # Move all songs to the existing performer
                            for song in performer.songs.all():
                                song.performer = existing_performer
                                song.save()

                            # Delete the duplicate performer
                            performer.delete()
                            self.stdout.write(f"  Deleted duplicate performer ID {performer.id}")
                    else:
                        # No duplicate, just update the names
                        performer.name = new_name
                        performer.name_kana = new_name_kana
                        performer.name_romaji = new_name_romaji
                        performer.save()

                    updated_count += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"\n\nDRY RUN: Would update {performers_to_update.count()} performer(s)")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"\n\nSuccessfully updated {updated_count} performer(s)"))
