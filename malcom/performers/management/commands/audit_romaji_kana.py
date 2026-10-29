"""List Performer and LiveHouse records whose kana/romaji readings are unusable for TTS.

A record is flagged when ``name_kana`` or ``name_romaji`` is blank, or when ``name_romaji``
still contains Japanese script (kana/kanji), which TTS reads as if no romaji existed.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandParser
from houses.models import LiveHouse

from performers.models import Performer

JAPANESE_SCRIPT_PATTERN = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")


def _issues(record: Performer | LiveHouse) -> list[str]:
    issues = []
    if not record.name_kana.strip():
        issues.append("blank kana")
    if not record.name_romaji.strip():
        issues.append("blank romaji")
    elif JAPANESE_SCRIPT_PATTERN.search(record.name_romaji):
        issues.append("romaji not romanized")
    return issues


def audit(records: list[Performer | LiveHouse]) -> list[dict]:
    flagged = []
    for record in records:
        if issues := _issues(record):
            flagged.append({"model": type(record).__name__, "pk": record.pk, "name": record.name, "issues": issues})
    return flagged


class Command(BaseCommand):
    help = "List Performer and LiveHouse records with blank name_kana/name_romaji or non-romanized name_romaji."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--active-days",
            type=int,
            default=None,
            help="Only audit performers with a performance in the last N days (default: all performers).",
        )
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Output format (default: text).",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        performers = Performer.objects.order_by("pk")
        if options["active_days"] is not None:
            since = date.today() - timedelta(days=options["active_days"])  # noqa: DTZ011
            performers = performers.filter(performance_schedules__performance_date__gte=since).distinct()

        flagged = audit([*performers, *LiveHouse.objects.order_by("pk")])

        if options["format"] == "json":
            self.stdout.write(json.dumps(flagged, ensure_ascii=False, indent=2))
            return
        for item in flagged:
            self.stdout.write(f"{item['model']}\t{item['pk']}\t{item['name']}\t{', '.join(item['issues'])}")
        self.stdout.write(f"{len(flagged)} flagged")
