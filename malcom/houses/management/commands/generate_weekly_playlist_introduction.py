"""Generate playlist introduction text and audio for a given WeeklyPlaylist."""

import asyncio
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from houses.functions import ROBOTIC_VOICE_PRESETS, generate_robotic_tts, generate_weekly_playlist_introduction_text
from houses.models import WeeklyPlaylist


class Command(BaseCommand):
    help = "Generate introduction text and optional robotic TTS audio for a weekly playlist using AI"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "playlist_id",
            type=int,
            help="ID of the WeeklyPlaylist to generate introduction for",
        )
        parser.add_argument(
            "--voice",
            type=str,
            choices=list(ROBOTIC_VOICE_PRESETS.keys()),
            default="emergency_broadcast",
            help="Robotic voice preset to use (default: emergency_broadcast)",
        )
        parser.add_argument(
            "--static",
            type=int,
            default=5,
            help="Static percentage (0-100, default: 5%%)",
        )
        parser.add_argument(
            "--audio",
            action="store_true",
            help="Generate TTS audio file in addition to text",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            help="Output directory for audio file (default: data/playlist_audio/)",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        """Generate and output playlist introduction text and optional audio."""
        playlist_id = options["playlist_id"]
        voice_preset = options["voice"]
        static_percentage = options["static"]
        generate_audio = options["audio"]
        output_dir = options["output_dir"]

        # Validate static percentage
        if not 0 <= static_percentage <= 100:  # noqa: PLR2004
            self.stderr.write(self.style.ERROR("Static percentage must be between 0 and 100"))
            return

        try:
            playlist = WeeklyPlaylist.objects.get(id=playlist_id)
        except WeeklyPlaylist.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"WeeklyPlaylist with id={playlist_id} not found"))
            return

        self.stdout.write(f"Generating introduction for playlist: week of {playlist.date.strftime('%Y-%m-%d')}")
        self.stdout.write(f"Playlist URL: {playlist.youtube_playlist_url}")
        self.stdout.write("")

        # Generate introduction text
        result_introduction, _ = generate_weekly_playlist_introduction_text(playlist)

        # Output the result
        self.stdout.write(self.style.SUCCESS("\n=== Generated Introduction ===\n"))
        self.stdout.write(result_introduction)

        # Generate TTS audio if requested
        if generate_audio:
            self.stdout.write("\n")
            self.stdout.write(self.style.SUCCESS("=== Generating TTS Audio ==="))
            self.stdout.write(f"Voice preset: {voice_preset} ({ROBOTIC_VOICE_PRESETS[voice_preset]['description']})")
            self.stdout.write(f"Static percentage: {static_percentage}%")

            # Set output directory
            if output_dir:
                audio_output_path = Path(output_dir)
            else:
                audio_output_path = Path(settings.BASE_DIR) / "data" / "playlist_audio"

            audio_output_path.mkdir(parents=True, exist_ok=True)

            # Generate audio filename
            audio_filename = f"playlist_{playlist.id}_week_{playlist.date.strftime('%Y%m%d')}_{voice_preset}.mp3"
            audio_file_path = audio_output_path / audio_filename

            try:
                # Generate robotic TTS audio
                asyncio.run(
                    generate_robotic_tts(
                        result_introduction,
                        audio_file_path,
                        voice_preset=voice_preset,
                        static_percentage=float(static_percentage),
                    )
                )

                self.stdout.write(self.style.SUCCESS(f"\n Audio saved to: {audio_file_path}"))

            except Exception as e:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(f"\n Audio generation failed: {e}"))
