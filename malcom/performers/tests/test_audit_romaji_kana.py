"""Tests for the audit_romaji_kana management command and the blank kana/romaji validators."""

from __future__ import annotations

import json
from datetime import date, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from houses.models import LiveHouse, LiveHouseWebsite, PerformanceSchedule

from performers.models import Performer


def _make_performer(name: str, name_kana: str, name_romaji: str) -> Performer:
    performer = Performer(name=name, name_kana=name_kana, name_romaji=name_romaji)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    return performer


def _make_venue(name: str = "Test Venue", name_kana: str = "テスト", name_romaji: str = "Test") -> LiveHouse:
    website = LiveHouseWebsite.objects.create(url=f"https://example.com/{name_romaji}")
    return LiveHouse.objects.create(
        website=website,
        name=name,
        name_kana=name_kana,
        name_romaji=name_romaji,
        address="addr",
        capacity=100,
        opened_date=date(2000, 1, 1),
    )


def _run(*args: str) -> list[dict]:
    out = StringIO()
    call_command("audit_romaji_kana", "--format", "json", *args, stdout=out)
    return json.loads(out.getvalue())


class AuditRomajiKanaCommandTestCase(TestCase):
    def test_flags_blank_kana_and_romaji(self):
        performer = _make_performer("破滅ロマンス", "", "")
        venue = _make_venue(name="Blank Venue", name_kana="", name_romaji="")

        flagged = _run()

        self.assertIn(
            {
                "model": "Performer",
                "pk": performer.pk,
                "name": "破滅ロマンス",
                "issues": ["blank kana", "blank romaji"],
            },
            flagged,
        )
        self.assertIn(
            {"model": "LiveHouse", "pk": venue.pk, "name": "Blank Venue", "issues": ["blank kana", "blank romaji"]},
            flagged,
        )

    def test_flags_romaji_containing_japanese_script(self):
        performer = _make_performer("ライティライト", "ライティライト", "ライティライト")

        flagged = _run()

        self.assertEqual(
            flagged,
            [{"model": "Performer", "pk": performer.pk, "name": "ライティライト", "issues": ["romaji not romanized"]}],
        )

    def test_complete_records_are_not_flagged(self):
        _make_performer("破滅ロマンス", "はめつろまんす", "hametsuromansu")
        _make_performer("THE POGO", "THE POGO", "THE POGO")
        _make_venue()

        self.assertEqual(_run(), [])

    def test_active_days_limits_performers_to_recent_schedules(self):
        venue = _make_venue()
        recent = _make_performer("最近", "", "")
        _make_performer("昔", "むかし", "むかし")
        schedule = PerformanceSchedule.objects.create(
            live_house=venue,
            performance_date=date.today() - timedelta(days=3),  # noqa: DTZ011
        )
        schedule.performers.add(recent)

        flagged = _run("--active-days", "30")

        self.assertEqual([(f["model"], f["pk"]) for f in flagged], [("Performer", recent.pk)])

    def test_text_output_lists_flagged_records(self):
        performer = _make_performer("破滅ロマンス", "", "")
        out = StringIO()

        call_command("audit_romaji_kana", stdout=out)

        self.assertIn(f"Performer\t{performer.pk}\t破滅ロマンス\tblank kana, blank romaji", out.getvalue())
        self.assertIn("1 flagged", out.getvalue())


class BlankNameReadingValidationTestCase(TestCase):
    def test_performer_blank_romaji_raises(self):
        performer = Performer(name="破滅ロマンス", name_kana="はめつろまんす", name_romaji=" ")

        with self.assertRaises(ValidationError) as ctx:
            performer.clean()

        self.assertEqual(set(ctx.exception.message_dict), {"name_romaji"})

    def test_performer_populated_readings_pass(self):
        Performer(name="破滅ロマンス", name_kana="はめつろまんす", name_romaji="hametsuromansu").clean()

    def test_livehouse_blank_kana_raises(self):
        venue = LiveHouse(name="Venue", name_kana="", name_romaji="Venue")

        with self.assertRaises(ValidationError) as ctx:
            venue.clean()

        self.assertEqual(set(ctx.exception.message_dict), {"name_kana"})

    def test_livehouse_populated_readings_pass(self):
        LiveHouse(name="Venue", name_kana="ベニュー", name_romaji="Venue").clean()
