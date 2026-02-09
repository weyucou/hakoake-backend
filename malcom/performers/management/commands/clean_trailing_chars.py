"""Management command to clean trailing slashes/backslashes from performer and song data."""

from django.core.management.base import BaseCommand

from performers.models import Performer, PerformerSong


class Command(BaseCommand):
    help = "Remove trailing slashes/backslashes from performer names and song titles"

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )

    def handle(self, *args, **options):  # noqa: ANN002, ANN003
        """Clean trailing slashes/backslashes from names and titles."""
        dry_run = options.get("dry_run", False)

        # Clean performer names
        performers_updated = 0
        performers = Performer.objects.all()

        self.stdout.write("\n=== Checking Performers ===\n")
        for performer in performers:
            old_name = performer.name
            old_name_kana = performer.name_kana
            old_name_romaji = performer.name_romaji

            # Clean the names
            new_name = performer.name.strip().rstrip("/\\") if performer.name else ""
            new_name_kana = performer.name_kana.strip().rstrip("/\\") if performer.name_kana else ""
            new_name_romaji = performer.name_romaji.strip().rstrip("/\\") if performer.name_romaji else ""

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
                    performer.name = new_name
                    performer.name_kana = new_name_kana
                    performer.name_romaji = new_name_romaji
                    performer.save()
                    performers_updated += 1

        # Clean song titles
        songs_updated = 0
        songs = PerformerSong.objects.all()

        self.stdout.write("\n\n=== Checking Songs ===\n")
        for song in songs:
            old_title = song.title

            # Clean the title
            new_title = song.title.strip().rstrip("/\\") if song.title else ""

            if old_title != new_title:
                self.stdout.write(f"\nSong ID {song.id} ({song.performer.name}):")
                self.stdout.write(f"  title: '{old_title}' → '{new_title}'")

                if not dry_run:
                    song.title = new_title
                    song.save()
                    songs_updated += 1

        # Summary
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\n\nDRY RUN: Would update {performers_updated} performer(s) and {songs_updated} song(s)"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n\nSuccessfully updated {performers_updated} performer(s) and {songs_updated} song(s)"
                )
            )
