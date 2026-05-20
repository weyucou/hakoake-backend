"""Regression test: transcript must state the correct band count (issue #74)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase
from performers.models import Performer, PerformerSong

from houses.functions import generate_weekly_playlist_introduction_text
from houses.models import WeeklyPlaylist, WeeklyPlaylistEntry


def _make_performer(name: str) -> Performer:
    performer = Performer(name=name, name_kana=name, name_romaji=name)
    performer._skip_image_fetch = True  # noqa: SLF001
    performer.save()
    return performer


def _make_song(performer: Performer, video_id: str = "abc123") -> PerformerSong:
    return PerformerSong.objects.create(
        performer=performer,
        title=f"{performer.name} Song",
        youtube_video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        youtube_view_count=1000,
        youtube_duration_seconds=200,
    )


class TestGenerateIntroductionTextBandCount(TestCase):
    """Verify the LLM prompt receives the exact playlist entry count."""

    def setUp(self) -> None:
        self.playlist = WeeklyPlaylist.objects.create(
            date=date(2026, 5, 19),
            youtube_playlist_id="PLtest",
            youtube_playlist_url="https://www.youtube.com/playlist?list=PLtest",
        )
        performers = [_make_performer(f"Band{i}") for i in range(1, 6)]
        for i, performer in enumerate(performers, start=1):
            song = _make_song(performer, video_id=f"vid{i:03d}")
            WeeklyPlaylistEntry.objects.create(playlist=self.playlist, song=song, position=i)

    @patch("houses.functions.ollama.chat")
    def test_prompt_contains_exact_entry_count(self, mock_ollama: MagicMock) -> None:
        """The user query sent to Ollama must state exactly 5 artists when 5 entries exist."""
        mock_ollama.return_value = {
            "message": {
                "content": (
                    "# INTRO\nFive bands.\n"
                    "# PERFORMER 1: Band1\nBand1 text.\n"
                    "# PERFORMER 2: Band2\nBand2 text.\n"
                    "# PERFORMER 3: Band3\nBand3 text.\n"
                    "# PERFORMER 4: Band4\nBand4 text.\n"
                    "# PERFORMER 5: Band5\nBand5 text.\n"
                    "# CLOSING\nClosing text.\n"
                )
            }
        }

        generate_weekly_playlist_introduction_text(self.playlist)

        mock_ollama.assert_called_once()
        call_messages = mock_ollama.call_args[1]["messages"]
        user_message = next(m["content"] for m in call_messages if m["role"] == "user")
        assert "exactly 5 selected artists" in user_message, (
            f"Expected 'exactly 5 selected artists' in user query, got:\n{user_message[:500]}"
        )
