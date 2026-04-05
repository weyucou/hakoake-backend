"""
Creates an intro video for a WeeklyPlaylist.

This command:
1. Takes a playlist ID
2. Generates video slides for each artist/song in the playlist
3. Includes artist info, performance dates/venues, and QR codes
4. Outputs an MP4 video file

Usage:
    python manage.py create_weekly_playlist_intro_video <playlist_id> [--output OUTPUT_PATH]
"""

import logging
from datetime import timedelta
from pathlib import Path

from commons.instagram_images import generate_qr_code
from django.core.management import BaseCommand, CommandParser
from houses.models import PerformanceSchedule, WeeklyPlaylist
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Video settings
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
SLIDE_DURATION = 7  # seconds per artist

# Design settings
BACKGROUND_COLOR = (20, 20, 30)  # Dark blue-gray
TEXT_COLOR = (255, 255, 255)  # White
ACCENT_COLOR = (255, 100, 100)  # Coral/pink
QR_BORDER_COLOR = (100, 100, 255)  # Light blue

# Font sizes (will be scaled if custom fonts not available)
TITLE_FONT_SIZE = 80
ARTIST_FONT_SIZE = 60
INFO_FONT_SIZE = 40
SMALL_FONT_SIZE = 30


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Get font with fallback to default if custom fonts unavailable."""
    try:
        # Try to use system fonts
        font_path = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        return ImageFont.truetype(font_path, size)
    except Exception:  # noqa: BLE001
        logger.warning(f"Could not load custom font, using default (size {size})")
        return ImageFont.load_default()


def create_artist_slide(
    artist_name: str,
    song_title: str,
    performances: list[PerformanceSchedule],
    qr_url: str,
    playlist_title: str,
) -> Image.Image:
    """Create a slide image for an artist."""
    # Create blank image
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(img)

    # Load fonts
    title_font = get_font(TITLE_FONT_SIZE, bold=True)
    artist_font = get_font(ARTIST_FONT_SIZE, bold=True)
    info_font = get_font(INFO_FONT_SIZE)
    small_font = get_font(SMALL_FONT_SIZE)

    # Draw playlist title at top
    title_y = 50
    draw.text((VIDEO_WIDTH // 2, title_y), playlist_title, font=title_font, fill=ACCENT_COLOR, anchor="mt")

    # Draw artist name
    artist_y = 250
    draw.text((VIDEO_WIDTH // 2, artist_y), artist_name, font=artist_font, fill=TEXT_COLOR, anchor="mt")

    # Draw song title
    song_y = artist_y + 100
    draw.text((VIDEO_WIDTH // 2, song_y), f'"{song_title}"', font=info_font, fill=(200, 200, 200), anchor="mt")

    # Draw performance information
    perf_y_start = song_y + 120
    if performances:
        draw.text(
            (100, perf_y_start),
            "Upcoming Performances:",
            font=info_font,
            fill=ACCENT_COLOR,
        )

        perf_y = perf_y_start + 60
        max_performances = 5  # Show max 5 performances
        for i, perf in enumerate(performances[:max_performances]):
            if i >= max_performances:
                break

            # Format: "Nov 15 @ Club Malcolm - 19:00"
            date_str = perf.performance_date.strftime("%b %d")
            time_str = perf.start_time.strftime("%H:%M") if perf.start_time else "TBA"
            venue_name = perf.live_house.name

            perf_text = f"  - {date_str} @ {venue_name} - {time_str}"
            draw.text((100, perf_y), perf_text, font=small_font, fill=TEXT_COLOR)
            perf_y += 50

        if len(performances) > max_performances:
            draw.text(
                (100, perf_y),
                f"  ... and {len(performances) - max_performances} more",
                font=small_font,
                fill=(150, 150, 150),
            )
    else:
        draw.text(
            (100, perf_y_start),
            "No upcoming performances found",
            font=info_font,
            fill=(150, 150, 150),
        )

    # Generate and place QR code
    qr_size = 300
    qr_img = generate_qr_code(qr_url, qr_size)

    # Add border to QR code
    qr_border = 10
    qr_with_border = Image.new("RGB", (qr_size + qr_border * 2, qr_size + qr_border * 2), QR_BORDER_COLOR)
    qr_with_border.paste(qr_img, (qr_border, qr_border))

    # Position QR code in bottom right
    qr_x = VIDEO_WIDTH - qr_size - qr_border * 2 - 100
    qr_y = VIDEO_HEIGHT - qr_size - qr_border * 2 - 100
    img.paste(qr_with_border, (qr_x, qr_y))

    # Add QR code label
    qr_label_y = qr_y - 40
    draw.text(
        (qr_x + (qr_size + qr_border * 2) // 2, qr_label_y),
        "Scan for details",
        font=small_font,
        fill=TEXT_COLOR,
        anchor="mm",
    )

    return img


class Command(BaseCommand):
    help = "Create an intro video for a weekly playlist"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "playlist_id",
            type=int,
            help="ID of the WeeklyPlaylist to create video for",
        )
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            default=".",
            help="Output directory path (default: current directory)",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            default="https://hakoake.com",
            help="Base URL for QR codes (default: https://hakoake.com)",
        )
        parser.add_argument(
            "--duration",
            type=int,
            default=SLIDE_DURATION,
            help=f"Duration of each slide in seconds (default: {SLIDE_DURATION})",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003, C901, PLR0915
        playlist_id = options["playlist_id"]
        output_dir = Path(options["output"])
        base_url = options["base_url"].rstrip("/")
        slide_duration = options["duration"]

        # Validate output directory
        if not output_dir.exists():
            self.stderr.write(self.style.ERROR(f"Output directory does not exist: {output_dir}"))
            return

        # Fetch playlist
        try:
            playlist = WeeklyPlaylist.objects.get(id=playlist_id)
        except WeeklyPlaylist.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"WeeklyPlaylist with ID {playlist_id} not found"))
            return

        self.stdout.write(f"Creating intro video for playlist: week of {playlist.date}")

        # Get playlist entries
        entries = playlist.weeklyplaylistentry_set.select_related("song__performer").order_by("position")

        if not entries.exists():
            self.stderr.write(self.style.ERROR("No entries found in this playlist"))
            return

        self.stdout.write(f"Found {entries.count()} entries in playlist")

        # Check if moviepy is available
        try:
            from moviepy import ImageClip, concatenate_videoclips  # noqa: PLC0415
        except ImportError:
            self.stderr.write(self.style.ERROR("moviepy is not installed. Install it with: uv add moviepy"))
            return

        # Generate slides for each entry
        clips = []
        playlist_title = f"HAKKO-AKKEI WEEK {playlist.date.strftime('%Y-%m-%d')} [TOKYO]"

        for entry in entries:
            performer = entry.song.performer
            song = entry.song

            self.stdout.write(f"\nGenerating slide {entry.position}/{entries.count()}: {performer.name}")

            # Find performances for this performer in the playlist week and beyond
            week_start = playlist.date
            week_end = week_start + timedelta(days=14)  # Look 2 weeks ahead

            performances = (
                PerformanceSchedule.objects.filter(
                    performers=performer,
                    performance_date__gte=week_start,
                    performance_date__lte=week_end,
                )
                .select_related("live_house")
                .order_by("performance_date", "start_time")
            )

            self.stdout.write(f"  Found {performances.count()} performances")

            # Generate QR code URL (performer detail page)
            qr_url = f"{base_url}/performers/{performer.id}/"

            # Create slide
            slide_img = create_artist_slide(
                artist_name=performer.name,
                song_title=song.title,
                performances=list(performances),
                qr_url=qr_url,
                playlist_title=playlist_title,
            )

            # Save slide as temporary image (for debugging)
            temp_slide_path = output_dir / f"slide_{entry.position:02d}.png"
            slide_img.save(temp_slide_path)
            self.stdout.write(f"  Saved slide: {temp_slide_path}")

            # Create video clip from image
            clip = ImageClip(str(temp_slide_path)).with_duration(slide_duration)
            clips.append(clip)

        # Concatenate all clips
        self.stdout.write("\nCombining clips into video...")
        final_video = concatenate_videoclips(clips, method="compose")

        # Generate output filename
        output_filename = f"playlist_{playlist_id}_week_{playlist.date.strftime('%Y%m%d')}_intro.mp4"
        output_path = output_dir / output_filename

        # Export video
        self.stdout.write(f"Exporting video to: {output_path}")
        final_video.write_videofile(
            str(output_path),
            fps=VIDEO_FPS,
            codec="libx264",
            audio=False,
            preset="medium",
            logger=None,  # Suppress moviepy verbose output
        )

        # Cleanup
        final_video.close()
        for clip in clips:
            clip.close()

        self.stdout.write(self.style.SUCCESS(f"\n Video created successfully: {output_path}"))
        self.stdout.write(f"  Duration: {len(clips) * slide_duration} seconds")
        self.stdout.write(f"  Resolution: {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
        self.stdout.write(f"  Slides: {len(clips)}")
