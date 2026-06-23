"""Audit PerformerSong records for likely mismatches.

A song is flagged as suspicious when:
1. The video title does NOT start with the performer name (weak artist signal), AND
2. No channel name is recorded (channel_name is not stored on PerformerSong) so we
   fall back to checking whether the performer name appears anywhere in the title.

This surfaces legacy rows created before the channel-match gate was added to
search_and_create_performer_songs (see issue #131).
"""

import re

from django.core.management.base import BaseCommand, CommandParser

from performers.models import PerformerSong


class Command(BaseCommand):
    help = (
        "Audit PerformerSong records for likely channel mismatches. "
        "Reports songs whose title does not start with the performer name — "
        "these are candidates for manual review or deletion."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete flagged songs (default: report only)",
        )
        parser.add_argument(
            "--performer-ids",
            nargs="+",
            type=int,
            default=None,
            help="Limit audit to specific performer IDs",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        delete: bool = options["delete"]
        performer_ids: list[int] | None = options.get("performer_ids")

        qs = PerformerSong.objects.select_related("performer").order_by("performer__name", "title")
        if performer_ids:
            qs = qs.filter(performer__id__in=performer_ids)

        flagged: list[PerformerSong] = []
        for song in qs:
            performer_lower = song.performer.name.lower().strip()
            title_lower = song.title.lower()
            if title_lower.startswith(performer_lower):
                continue
            # Also skip when the performer name appears verbatim anywhere in the title
            # (e.g. Japanese-name performers whose title is in kanji then the romaji
            # name in parentheses).
            if re.search(rf"\b{re.escape(performer_lower)}\b", title_lower):
                continue
            flagged.append(song)

        if not flagged:
            self.stdout.write(self.style.SUCCESS("No suspicious songs found."))
            return

        self.stdout.write(
            self.style.WARNING(f"Found {len(flagged)} suspicious song(s) (title does not start with performer name):\n")
        )
        for song in flagged:
            self.stdout.write(
                f"  [song id={song.id}] performer='{song.performer.name}' (id={song.performer.id})\n"
                f"    title: {song.title}\n"
                f"    url:   {song.youtube_url}\n"
            )

        if delete:
            ids = [s.id for s in flagged]
            PerformerSong.objects.filter(id__in=ids).delete()
            self.stdout.write(self.style.SUCCESS(f"\nDeleted {len(flagged)} song(s)."))
        else:
            self.stdout.write("\nRun with --delete to remove these songs, or review them manually via the admin.")
