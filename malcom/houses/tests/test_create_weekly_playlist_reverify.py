"""Tests for the ``_reverify_legacy_song_durations`` step in create_weekly_playlist.

Context: a 41-minute live recording (the 流血ブリザード "Namba Rockets" entry that
shipped in the 2026-04-06 weekly playlist) was stored with a stale, much smaller
``youtube_duration_seconds`` value. The DB row had been written by an earlier
ingestion path; subsequent extractions agreed on a longer duration but the row
was never refreshed. The pre-pass added in this fix re-fetches durations for any
candidate PerformerSong row whose ``updated_datetime`` is before
``DURATION_REVERIFICATION_CUTOFF_DATE`` and rewrites the DB before the playlist
duration filter is applied. Every processed row's ``updated_datetime`` is then
bumped so subsequent runs skip the row.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase
from performers.models import Performer, PerformerSong

from houses.management.commands.create_weekly_playlist import (
    DURATION_REVERIFICATION_CUTOFF_DATE,
    Command,
)

# Use settings-aware bounds (matches the command)
MIN_S = settings.MIN_SONG_SELECTION_DURATION_SECONDS
MAX_S = settings.MAX_SONG_SELECTION_DURATION_MINUTES * 60


def _make_performer(name: str) -> Performer:
    p = Performer(name=name, name_kana=name, name_romaji=name)
    p._skip_image_fetch = True  # noqa: SLF001
    p.save()
    return p


def _make_song(
    performer: Performer,
    *,
    duration_seconds: int,
    video_id: str,
    created_datetime: datetime,
    updated_datetime: datetime | None = None,
) -> PerformerSong:
    song = PerformerSong.objects.create(
        performer=performer,
        title=f"{video_id} ({duration_seconds}s)",
        youtube_video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        youtube_view_count=10000,
        youtube_duration_seconds=duration_seconds,
    )
    # auto_now / auto_now_add bypass: rewrite both timestamps after insert.
    # Defaults updated_datetime to created_datetime so the row is treated as
    # legacy unless the test explicitly says otherwise.
    if updated_datetime is None:
        updated_datetime = created_datetime
    PerformerSong.objects.filter(pk=song.pk).update(
        created_datetime=created_datetime,
        updated_datetime=updated_datetime,
    )
    song.refresh_from_db()
    return song


# Sentinel datetimes for legacy / fresh song rows
_LEGACY_DATETIME = datetime.combine(
    DURATION_REVERIFICATION_CUTOFF_DATE - timedelta(days=10),
    datetime.min.time(),
    tzinfo=UTC,
)
_FRESH_DATETIME = datetime.combine(
    DURATION_REVERIFICATION_CUTOFF_DATE + timedelta(days=1),
    datetime.min.time(),
    tzinfo=UTC,
)


class TestReverifyLegacySongDurations(TestCase):
    """Direct tests for ``Command._reverify_legacy_song_durations``."""

    def setUp(self) -> None:
        self.command = Command()
        self.command.stdout = MagicMock()
        self.performer = _make_performer("test_performer")
        self.secrets_file = Path("/tmp/client_secret.json")  # noqa: S108

    @patch("houses.management.commands.create_weekly_playlist.get_video_durations")
    def test_legacy_song_with_stale_short_duration_updated_to_actual(self, mock_get_durations: MagicMock) -> None:
        """A legacy song claiming 30s but actually 2472s (41:12) should be rewritten."""
        actual_seconds = 41 * 60 + 12  # 2472, well above the 12-minute max
        song = _make_song(
            self.performer,
            duration_seconds=30,
            video_id="vid_legacy_long",
            created_datetime=_LEGACY_DATETIME,
        )
        mock_get_durations.return_value = {"vid_legacy_long": actual_seconds}

        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )

        song.refresh_from_db()
        self.assertEqual(song.youtube_duration_seconds, actual_seconds)
        # updated_datetime must have moved past the cutoff so the row is skipped next run
        self.assertGreaterEqual(
            song.updated_datetime.date(),
            DURATION_REVERIFICATION_CUTOFF_DATE,
        )
        mock_get_durations.assert_called_once_with(["vid_legacy_long"], self.secrets_file)

    @patch("houses.management.commands.create_weekly_playlist.get_video_durations")
    def test_matching_duration_leaves_value_alone_but_bumps_updated_datetime(
        self, mock_get_durations: MagicMock
    ) -> None:
        """If YouTube confirms the existing duration, the value is unchanged but
        ``updated_datetime`` must still be bumped so subsequent runs skip the row.
        """
        song = _make_song(
            self.performer,
            duration_seconds=180,
            video_id="vid_legacy_ok",
            created_datetime=_LEGACY_DATETIME,
        )
        mock_get_durations.return_value = {"vid_legacy_ok": 180}

        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )

        song.refresh_from_db()
        self.assertEqual(song.youtube_duration_seconds, 180)
        self.assertGreaterEqual(
            song.updated_datetime.date(),
            DURATION_REVERIFICATION_CUTOFF_DATE,
        )

    @patch("houses.management.commands.create_weekly_playlist.get_video_durations")
    def test_song_with_recent_updated_datetime_skipped(self, mock_get_durations: MagicMock) -> None:
        """A song whose ``updated_datetime`` is on/after the cutoff must NOT be
        re-verified — this covers both freshly-ingested rows and rows that have
        already been touched by a previous re-verification run.
        """
        _make_song(
            self.performer,
            duration_seconds=180,
            video_id="vid_recently_touched",
            created_datetime=_LEGACY_DATETIME,
            updated_datetime=_FRESH_DATETIME,
        )
        mock_get_durations.return_value = {}

        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )

        # No candidates → API must not be called
        mock_get_durations.assert_not_called()

    @patch("houses.management.commands.create_weekly_playlist.get_video_durations")
    def test_second_run_is_idempotent(self, mock_get_durations: MagicMock) -> None:
        """After a row has been re-verified once, a second run must NOT include it
        in the candidate set (because the first run bumped ``updated_datetime``).
        """
        _make_song(
            self.performer,
            duration_seconds=180,
            video_id="vid_legacy_idempotent",
            created_datetime=_LEGACY_DATETIME,
        )
        mock_get_durations.return_value = {"vid_legacy_idempotent": 180}

        # First run — should fetch
        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )
        self.assertEqual(mock_get_durations.call_count, 1)

        # Second run — row's updated_datetime is now past the cutoff, so the
        # candidate query returns nothing and the API is NOT called again
        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )
        self.assertEqual(mock_get_durations.call_count, 1)

    @patch("houses.management.commands.create_weekly_playlist.get_video_durations")
    def test_legacy_song_already_out_of_range_not_reverified(self, mock_get_durations: MagicMock) -> None:
        """Songs already excluded by the duration filter cannot be selected, so we
        do not waste API quota re-verifying them.
        """
        _make_song(
            self.performer,
            duration_seconds=MAX_S + 1,  # already too long
            video_id="vid_legacy_too_long",
            created_datetime=_LEGACY_DATETIME,
        )
        mock_get_durations.return_value = {}

        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )

        mock_get_durations.assert_not_called()

    @patch("houses.management.commands.create_weekly_playlist.get_video_durations")
    def test_unavailable_video_marked_as_zero_duration(self, mock_get_durations: MagicMock) -> None:
        """If YouTube no longer returns the video, set duration=0 so it's filtered out
        and bump ``updated_datetime`` so the row is not re-checked next run.
        """
        song = _make_song(
            self.performer,
            duration_seconds=180,
            video_id="vid_legacy_deleted",
            created_datetime=_LEGACY_DATETIME,
        )
        mock_get_durations.return_value = {}  # video missing from API response

        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )

        song.refresh_from_db()
        self.assertEqual(song.youtube_duration_seconds, 0)
        self.assertGreaterEqual(
            song.updated_datetime.date(),
            DURATION_REVERIFICATION_CUTOFF_DATE,
        )

    @patch("houses.management.commands.create_weekly_playlist.get_video_durations")
    def test_multiple_legacy_songs_batch_in_one_call(self, mock_get_durations: MagicMock) -> None:
        """All legacy candidates for eligible performers should be batched into a
        single ``get_video_durations`` call.
        """
        ids = []
        for i in range(3):
            video_id = f"vid_legacy_{i}"
            _make_song(
                self.performer,
                duration_seconds=120 + i,
                video_id=video_id,
                created_datetime=_LEGACY_DATETIME,
            )
            ids.append(video_id)
        mock_get_durations.return_value = dict.fromkeys(ids, 200)

        self.command._reverify_legacy_song_durations(  # noqa: SLF001
            [self.performer], MIN_S, MAX_S, self.secrets_file
        )

        self.assertEqual(mock_get_durations.call_count, 1)
        called_ids = mock_get_durations.call_args[0][0]
        self.assertEqual(sorted(called_ids), sorted(ids))

    def test_cutoff_date_is_2026_03_30(self) -> None:
        """Anchor the cutoff date so accidental drift is caught by tests."""
        self.assertEqual(DURATION_REVERIFICATION_CUTOFF_DATE, date(2026, 3, 30))
