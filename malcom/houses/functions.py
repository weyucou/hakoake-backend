import asyncio
import json
import logging
import random
import re
import tempfile
from datetime import datetime
from pathlib import Path

import edge_tts
import numpy as np
import ollama
import qrcode
from django.conf import settings
from django.core import management
from django.db.models import Count
from django.utils import timezone
from moviepy import AudioFileClip, CompositeAudioClip, ImageClip, concatenate_audioclips, concatenate_videoclips
from moviepy.audio import fx as afx
from performers.models import Performer, PerformerSocialLink
from PIL import Image, ImageDraw, ImageFont
from pydub import AudioSegment
from pydub.generators import WhiteNoise

from .crawlers import CrawlerRegistry
from .definitions import CrawlerCollectionState, WebsiteProcessingState
from .models import LiveHouse, LiveHouseWebsite, MonthlyPlaylist, MonthlyPlaylistEntry, PerformanceSchedule

logger = logging.getLogger(__name__)


APP_TEMPLATE_DIR = Path(__file__).parent / "templates"


# Robotic voice presets for TTS
ROBOTIC_VOICE_PRESETS = {
    "military": {
        "name": "robotic_military",
        "description": "Military-style robotic voice - authoritative",
        "edge_voice": "en-US-EricNeural",
        "rate": "+5%",
        "pitch": "-15Hz",
        "static_level": -12,
        "bitrate": "56k",
        "sample_rate": 12000,
    },
    "emergency_broadcast": {
        "name": "robotic_emergency_broadcast",
        "description": "Emergency broadcast - military style with light static",
        "edge_voice": "en-US-EricNeural",
        "rate": "+0%",
        "pitch": "-22Hz",
        "static_level": -17,
        "bitrate": "64k",
        "sample_rate": 16000,
    },
}


async def generate_robotic_tts(
    text: str,
    output_path: Path,
    voice_preset: str = "emergency_broadcast",
    static_percentage: float = 5.0,
) -> None:
    """Generate TTS audio with robotic effects.

    Args:
        text: Text to convert to speech
        output_path: Path where the MP3 file will be saved
        voice_preset: Voice preset to use ("military" or "emergency_broadcast")
        static_percentage: Percentage of audio to apply static (0-100), default 5%
    """
    if voice_preset not in ROBOTIC_VOICE_PRESETS:
        msg = f"Invalid voice preset: {voice_preset}. Choose from: {list(ROBOTIC_VOICE_PRESETS.keys())}"
        raise ValueError(msg)

    preset = ROBOTIC_VOICE_PRESETS[voice_preset]

    # Generate base TTS audio using edge-tts
    logger.info(f"Generating TTS with voice: {preset['edge_voice']}")
    communicate = edge_tts.Communicate(text, preset["edge_voice"], rate=preset["rate"], pitch=preset["pitch"])
    await communicate.save(str(output_path))

    # Apply robotic effects
    logger.info(f"Applying robotic effects (static: {static_percentage:.1f}%)")

    # Load the audio
    audio = AudioSegment.from_mp3(str(output_path))

    # Convert percentage to probability (0-100 -> 0.0-1.0)
    static_probability = static_percentage / 100.0

    # Apply static intermittently
    chunk_duration_ms = 200  # 200ms chunks for static application
    chunks = []
    static_chunks_count = 0

    # Initialize random generator
    rng = np.random.default_rng()

    for chunk_start in range(0, len(audio), chunk_duration_ms):
        chunk = audio[chunk_start : chunk_start + chunk_duration_ms]

        # Random chance to add static to this chunk
        if rng.random() < static_probability:
            # Generate noise for this chunk only
            noise = WhiteNoise().to_audio_segment(duration=len(chunk))
            # Mix chunk with noise
            chunk = chunk.overlay(noise + preset["static_level"])
            static_chunks_count += 1

        chunks.append(chunk)

    robotic_audio = sum(chunks) if chunks else audio
    logger.info(f"Applied static to {static_chunks_count} chunks ({static_chunks_count * chunk_duration_ms}ms total)")

    # Apply quality reduction based on preset for more "digital" artifacts
    robotic_audio = robotic_audio.set_frame_rate(preset["sample_rate"])

    # Export with preset's bitrate for varied compression artifacts
    robotic_audio.export(str(output_path), format="mp3", bitrate=preset["bitrate"])
    logger.info(f"Robotic TTS audio saved to: {output_path}")


def collect_schedules(venue_id: int | None = None) -> None:
    """
    Collect schedules from registered LiveHouseWebsite objects by running their associated crawlers.
    Only crawl websites that haven't been successfully collected today.

    Args:
        venue_id: Optional LiveHouse ID. If provided, only collect schedules for this venue.
    """
    today = timezone.localdate()

    # Query all LiveHouseWebsite objects that have a crawler_class defined
    # and exclude those that have been successfully collected today
    websites = LiveHouseWebsite.objects.exclude(crawler_class="").exclude(crawler_class__isnull=True)

    # If venue_id is provided, filter to only that venue's website
    if venue_id is not None:
        websites = websites.filter(live_houses__id=venue_id)

    # Filter out websites where any associated LiveHouse was successfully collected today
    websites_to_exclude = set()
    for website in websites:
        live_houses_collected_today = website.live_houses.filter(
            last_collected_datetime__date=today, last_collection_state=CrawlerCollectionState.SUCCESS
        )
        if live_houses_collected_today.exists():
            websites_to_exclude.add(website.id)

    websites = websites.exclude(id__in=websites_to_exclude)

    logger.info(f"Found {websites.count()} websites to crawl (excluding already collected today)")
    if websites_to_exclude:
        logger.info(f"Skipped {len(websites_to_exclude)} websites already successfully collected today")

    success_count = 0
    failed_count = 0
    skipped_count = len(websites_to_exclude)

    for website in websites:
        # Get live house info for this website
        live_house = website.live_houses.first()
        live_house_name = live_house.name if live_house else "Unknown Live House"

        logger.info(f"🏠 Processing Live House: {live_house_name}")
        logger.info(f"   URL: {website.url}")
        logger.info(f"   Crawler: {website.crawler_class}")

        # Get before counts for comparison
        before_schedules = PerformanceSchedule.objects.filter(live_house=live_house).count() if live_house else 0
        before_performers = Performer.objects.count()

        try:
            # Run the crawler for this website
            CrawlerRegistry.run_crawler(website)
            success_count += 1

            # Get after counts for results
            after_schedules = PerformanceSchedule.objects.filter(live_house=live_house).count() if live_house else 0
            after_performers = Performer.objects.count()

            new_schedules = after_schedules - before_schedules
            new_performers = after_performers - before_performers

            logger.info(f"✅ Successfully crawled {live_house_name}")
            logger.info(f"   📅 Performance Schedules: {new_schedules} new ({after_schedules} total)")
            logger.info(f"   🎭 Performers: {new_performers} new ({after_performers} total)")
            if live_house:
                logger.info(f"   🎪 Venue Capacity: {live_house.capacity}")
            logger.info("")  # Empty line for readability

        except Exception:  # noqa: BLE001
            failed_count += 1
            logger.exception(f"❌ Failed to crawl {live_house_name} (URL: {website.url})")

            # The crawler should have already set the state to FAILED
            # but ensure it's set in case of unexpected errors
            website.state = WebsiteProcessingState.FAILED
            website.save()

    logger.info(f"Crawling complete: {success_count} successful, {failed_count} failed, {skipped_count} skipped")

    # After crawling, dump the data
    dump_collected_data()


def dump_collected_data() -> str:
    """
    Dump houses and performers app data to a timestamped JSON file.
    Returns the path to the created file.
    """
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")  # noqa: DTZ001
    filename = f"collected-{timestamp}.json"

    # Create data directory if it doesn't exist
    data_dir = Path(settings.BASE_DIR) / "data"
    data_dir.mkdir(exist_ok=True)

    filepath = data_dir / filename

    logger.info(f"Dumping data to {filepath}")

    # Use Django's dumpdata command to export houses and performers apps
    with open(filepath, "w") as f:  # noqa: PTH123
        management.call_command("dumpdata", "houses", "performers", format="json", indent=2, stdout=f)

    logger.info(f"Data dumped successfully to {filepath}")

    # Also create a summary
    create_collection_summary(filepath, timestamp)

    return str(filepath)


def create_collection_summary(data_filepath: Path, timestamp: str) -> None:  # noqa: C901, PLR0912, PLR0915, PLR0911
    """Create a summary of the collected data."""
    summary = {
        "collection_timestamp": timestamp,
        "statistics": {
            "live_houses": LiveHouse.objects.count(),
            "performance_schedules": PerformanceSchedule.objects.count(),
            "performers": Performer.objects.count(),
            "websites": {
                "total": LiveHouseWebsite.objects.count(),
                "completed": LiveHouseWebsite.objects.filter(state=WebsiteProcessingState.COMPLETED).count(),
                "failed": LiveHouseWebsite.objects.filter(state=WebsiteProcessingState.FAILED).count(),
                "not_started": LiveHouseWebsite.objects.filter(state=WebsiteProcessingState.NOT_STARTED).count(),
                "in_progress": LiveHouseWebsite.objects.filter(state=WebsiteProcessingState.IN_PROGRESS).count(),
            },
        },
        "data_file": data_filepath.name,
    }

    # Save summary
    summary_path = data_filepath.parent / f"collection-summary-{timestamp}.json"
    with open(summary_path, "w") as f:  # noqa: PTH123
        json.dump(summary, f, indent=2)

    logger.info(f"Summary saved to {summary_path}")
    logger.info("Collection Summary:")
    logger.info(f"  - Live Houses: {summary['statistics']['live_houses']}")
    logger.info(f"  - Performance Schedules: {summary['statistics']['performance_schedules']}")
    logger.info(f"  - Performers: {summary['statistics']['performers']}")
    logger.info(
        f"  - Websites crawled: {summary['statistics']['websites']['completed']}/{summary['statistics']['websites']['total']}"  # noqa: E501
    )


def parse_introduction_sections(introduction_text: str, expected_sections: int) -> list[dict[str, str]]:
    """
    Parse the introduction text into sections for each slide.

    Args:
        introduction_text: The full introduction text with section headers
        expected_sections: Total number of sections expected (intro + performers + closing)

    Returns:
        List of dicts with 'type' and 'text' keys for each section
    """
    sections = []

    # Split by section headers (# INTRO, # PERFORMER N:, # CLOSING)
    pattern = r"#\s+(INTRO|PERFORMER\s+\d+:.*?|CLOSING)\s*\n(.*?)(?=\n#\s+|$)"
    matches = re.findall(pattern, introduction_text, re.DOTALL | re.MULTILINE)

    for header, section_text in matches:
        section_text = section_text.strip()  # noqa: PLW2901
        if section_text:
            if header == "INTRO":
                sections.append({"type": "intro", "text": section_text})
            elif header == "CLOSING":
                sections.append({"type": "closing", "text": section_text})
            elif header.startswith("PERFORMER"):
                sections.append({"type": "performer", "text": section_text})

    # Validate section count
    if len(sections) != expected_sections:
        logger.warning(
            f"Section count mismatch: expected {expected_sections}, got {len(sections)}. "
            f"Will fall back to equal-duration slides."
        )
        return []

    return sections


def apply_robotic_effects_to_audio(audio_path: Path) -> None:
    """Apply robotic effects (static noise and quality reduction) to an audio file."""
    # Load the audio
    audio = AudioSegment.from_mp3(str(audio_path))

    # Create glitchy static at the end of the audio (550ms total)
    # Use fixed seed to ensure same glitchy pattern across all slides
    static_duration_ms = 550
    gap_silence_probability = 0.5  # 50% chance of silence vs quiet noise
    rng = random.Random(42)  # Fixed seed for consistent glitch pattern  # noqa: S311

    # Create glitchy static by combining multiple short bursts with varying levels and gaps
    glitch_static = AudioSegment.silent(duration=0)
    remaining_duration = static_duration_ms

    while remaining_duration > 0:
        # Random burst duration between 20-80ms (but consistent due to seed)
        burst_duration = min(rng.randint(20, 80), remaining_duration)

        # Create noise burst with level variation
        noise_burst = WhiteNoise().to_audio_segment(duration=burst_duration)
        level_variation = rng.uniform(-5.0, 5.0)
        varied_level = settings.EDGE_TTS_STATIC_LEVEL + level_variation
        noise_burst = noise_burst + varied_level

        # Add the burst
        glitch_static = glitch_static + noise_burst
        remaining_duration -= burst_duration

        # Add random gap (silence or very quiet noise) between bursts
        if remaining_duration > 0:
            gap_duration = min(rng.randint(5, 30), remaining_duration)
            if rng.random() < gap_silence_probability:
                # Complete silence
                gap = AudioSegment.silent(duration=gap_duration)
            else:
                # Very quiet noise
                gap = WhiteNoise().to_audio_segment(duration=gap_duration)
                gap = gap + (settings.EDGE_TTS_STATIC_LEVEL - 15)  # Much quieter
            glitch_static = glitch_static + gap
            remaining_duration -= gap_duration

    # Append glitchy static to the end
    robotic_audio = audio + glitch_static
    logger.info(f"Applied {static_duration_ms}ms glitchy static to end of audio")

    # Apply quality reduction for digital artifacts
    robotic_audio = robotic_audio.set_frame_rate(settings.EDGE_TTS_SAMPLE_RATE)

    # Export with configured bitrate
    robotic_audio.export(str(audio_path), format="mp3", bitrate=settings.EDGE_TTS_BITRATE)


def create_rgb_shift_effect(clip: ImageClip, shift_amount: int = 5) -> ImageClip:
    """Apply RGB channel shift effect for a glitch look."""

    def rgb_shift(get_frame, t):  # noqa: ANN001, ANN202
        """Shift RGB channels to create chromatic aberration effect."""
        frame = get_frame(t)
        shifted = frame.copy()

        # Shift red channel right
        shifted[:, shift_amount:, 0] = frame[:, :-shift_amount, 0]
        # Shift blue channel left
        shifted[:, :-shift_amount, 2] = frame[:, shift_amount:, 2]

        return shifted

    return clip.transform(rgb_shift)


def create_scanlines_effect(clip: ImageClip, line_height: int = 4, intensity: float = 0.3) -> ImageClip:
    """Add horizontal scanline effect."""

    def add_scanlines(get_frame, t):  # noqa: ANN001, ANN202
        """Add horizontal scanlines to the frame."""
        frame = get_frame(t).copy()
        h, w = frame.shape[:2]

        # Create scanline mask
        for y in range(0, h, line_height):
            frame[y : y + 2] = frame[y : y + 2] * (1 - intensity)

        return frame

    return clip.transform(add_scanlines)


def create_glitch_transition(last_frame_path: Path, duration: float = 0.1) -> ImageClip:
    """Create a short glitch transition clip using the last frame of previous slide."""
    # Load the last frame
    base_clip = ImageClip(str(last_frame_path)).with_duration(duration)

    # Apply multiple glitch effects
    glitched = create_rgb_shift_effect(base_clip, shift_amount=8)
    glitched = create_scanlines_effect(glitched, line_height=3, intensity=0.4)

    return glitched


def generate_playlist_introduction_text(playlist: MonthlyPlaylist) -> tuple[str, list]:
    playlist_intro_prompt_filepath = APP_TEMPLATE_DIR / "PLAYLIST_INTRO_PROMPT.md"
    assert playlist_intro_prompt_filepath.exists(), f"not found: {playlist_intro_prompt_filepath.resolve()}"
    playlist_intro_prompt = playlist_intro_prompt_filepath.read_text(encoding="utf8")

    messages = [
        {"role": "system", "content": playlist_intro_prompt},
    ]

    # Get the number of MonthlyPlaylistEntry items for each performer in other playlists
    # Returns dict: {performer_id: count, ...}
    performer_playlist_appearances = dict(
        MonthlyPlaylistEntry.objects.exclude(playlist=playlist)
        .values("song__performer")
        .annotate(count=Count("id"))
        .values_list("song__performer", "count")
    )

    # prepare playlist data:
    user_query = [
        f"For the month of {playlist.date.strftime('%B')} write an introduction to selected artists below, describing where and when they will play."  # noqa: E501
        "ALWAYS mention the date and day of the week when introduction where/when the artists play."
        "The site's description is as follows (DO NOT INCLUDE it in the result response, but consider it for flavor):\n"
        "Can't see the artist for your seat? Ditch the arenas and stadiums.\n"
        'Your new favorite band is playing in dark cramped basement bars, or "Live Houses".\n'
        'We\'ll help you find your way into the current Tokyo "Live House" scene, '
        "by spotlighting the lesser known bands playing in venues where you can "
        'actually "see" the artists.  '
        "We keep it intimate by only bringing you artists performing at low capacity venues!\n\n"
        "The text generated here is for a slide presentation voice-over.\n"
        "Clearly separate the START/EACH PERFORMER/END text, so they can be "
        "properly applied to the appropriate slide.\n"
        "Selected Artists/Performers (appear in the order they appear in the playlist):\n"
    ]
    # Calculate month boundaries for filtering performances
    month_start = playlist.date
    if playlist.date.month == 12:  # noqa: PLR2004
        month_end = playlist.date.replace(year=playlist.date.year + 1, month=1, day=1)
    else:
        month_end = playlist.date.replace(month=playlist.date.month + 1, day=1)

    playlist_entry_data = []
    for entry in playlist.monthlyplaylistentry_set.order_by("position"):
        entry_data = [
            f"{entry.position}. Artist: {entry.song.performer.name}\n",
            f"\t- name kana: {entry.song.performer.name_kana}\n",
            f"\t- name romaji: {entry.song.performer.name_romaji}\n",
            f"\t- website: {entry.song.performer.website}\n",
            f"\t- email: {entry.song.performer.email}\n",
            f"\t- song (youtube link title): {entry.song.title}\n",
            f"\t- youtube release date: {entry.song.release_date}\n",
            f"\t- playlist appearances: {performer_playlist_appearances.get(entry.song.performer.id, 0)}\n",
        ]
        if entry.song.performer.name_romaji:
            entry_data.append(
                f"\t- email: {entry.song.performer.name_romaji}\n",
            )

        if entry.is_spotlight:
            entry_data.append(
                "Monthly Spotlight Artist: True (This performer is a special spotlighted artist for this month!)"
            )

        for social in PerformerSocialLink.objects.filter(performer=entry.song.performer):
            entry_data.append(f"\t- {social.platform}: {social.url}\n")

        # Add performance schedule details for this month
        performances = (
            PerformanceSchedule.objects.filter(
                performers=entry.song.performer,
                performance_date__gte=month_start,
                performance_date__lt=month_end,
            )
            .select_related("live_house")
            .order_by("performance_date")
        )

        if performances.exists():
            entry_data.append(f"\t- performances in {playlist.date.strftime('%B %Y')}:\n")
            for perf in performances:
                entry_data.append(f"\t\t- date: {perf.performance_date.strftime('%Y-%m-%d (%a)')}\n")
                entry_data.append(f"\t\t  venue: {perf.live_house.name}\n")
                entry_data.append(f"\t\t  venue kana: {perf.live_house.name_kana}\n")
                entry_data.append(f"\t\t  venue romaji: {perf.live_house.name_romaji}\n")
                entry_data.append(f"\t\t  open: {perf.open_time.strftime('%H:%M') if perf.open_time else 'TBA'}\n")
                entry_data.append(f"\t\t  start: {perf.start_time.strftime('%H:%M') if perf.start_time else 'TBA'}\n")

        entry_data.append("\n")

        playlist_entry_data.extend(entry_data)
    user_query.extend(playlist_entry_data)
    messages.append({"role": "user", "content": "".join(user_query)})

    try:
        # Call Ollama API
        response = ollama.chat(model=settings.PLAYLIST_INTRO_TEXT_GENERATION_MODEL, messages=messages)
        # Extract the feedback text from the response
        result_introduction = response["message"]["content"]

    except ollama.ResponseError as e:
        logger.exception("Ollama API error occurred")
        http_not_found = 404
        if e.status_code == http_not_found:
            error_msg = (
                f"Model '{settings.PLAYLIST_INTRO_TEXT_GENERATION_MODEL}' not found. "
                f"Please run: ollama pull hf.co/mmnga/{settings.PLAYLIST_INTRO_TEXT_GENERATION_MODEL}"
            )
        else:
            error_msg = f"Ollama API error: {e.error}"
        logger.exception(error_msg)
        raise

    return result_introduction, playlist_entry_data


def generate_playlist_video(playlist: MonthlyPlaylist, intro_text: str | None = None) -> Path:  # noqa: C901, PLR0915, PLR0912
    """
    Generate a video for the monthly playlist with QR codes, slides, and TTS narration.

    Args:
        playlist: MonthlyPlaylist object to generate video for
        intro_text: Optional pre-written introduction text. If not provided, text will be generated using AI.
    """
    # Generate or use provided introduction text
    if intro_text:
        result_introduction = intro_text
        playlist_entry_data = []  # Not needed when using custom intro text
    else:
        result_introduction, playlist_entry_data = generate_playlist_introduction_text(playlist)

    # Create temp directory for assets
    temp_dir = Path(tempfile.mkdtemp())
    logger.info(f"Created temp directory: {temp_dir}")

    # Video settings
    video_width = 1920
    video_height = 1080
    slide_duration = 8  # seconds per slide
    bg_color = (20, 20, 30)  # Dark blue background
    text_color = (255, 255, 255)  # White text

    slides = []

    # Load background image
    background_image_path = Path(settings.BASE_DIR).parent / "static" / "hakkoake_slide_background_202511.png"
    background_image = None
    if background_image_path.exists():
        try:
            background_image = Image.open(background_image_path).convert("RGBA")
            # Resize to match video dimensions
            background_image = background_image.resize((video_width, video_height), Image.Resampling.LANCZOS)
            # Set 20% transparency (80% opacity = alpha 204)
            alpha = background_image.split()[3]  # Get alpha channel
            alpha = alpha.point(lambda p: int(p * 0.8))  # 80% opacity
            background_image.putalpha(alpha)
            logger.info(f"Loaded background image: {background_image_path}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to load background image: {e}")
            background_image = None
    else:
        logger.warning(f"Background image not found: {background_image_path}")

    # Helper function to create QR code
    def create_qr_code(url: str, size: int = 200) -> Image.Image:
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").resize((size, size))

    # Helper function to create slide
    def create_slide(  # noqa: C901, PLR0912, PLR0915
        title: str,
        subtitle: str = "",
        description: str = "",
        qr_urls: list[str] | None = None,
        qr_labels: list[str] | None = None,
    ) -> Image.Image:
        # Create base image with solid background color
        img = Image.new("RGB", (video_width, video_height), bg_color)

        # Apply background image if available (with 20% transparency)
        if background_image:
            # Convert to RGBA for compositing
            img = img.convert("RGBA")
            # Composite background image onto base
            img = Image.alpha_composite(img, background_image)
            # Convert back to RGB
            img = img.convert("RGB")

        draw = ImageDraw.Draw(img)

        # Try to load fonts that support Japanese characters
        # Priority: Noto Sans CJK (best quality) > DroidSansFallbackFull > DejaVu (fallback, no Japanese)
        try:
            # Try Noto Sans CJK Bold for titles (index 0 is Japanese)
            title_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 80, index=0)
        except (OSError, ValueError):
            try:
                # Fallback to DroidSansFallbackFull
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 80)
            except OSError:
                # Last resort: DejaVu (no Japanese support)
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)

        try:
            # Try Noto Sans CJK Regular for subtitles (index 0 is Japanese)
            subtitle_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 40, index=0)
        except (OSError, ValueError):
            try:
                subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 40)
            except OSError:
                subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)

        try:
            # Try Noto Sans CJK Regular for descriptions (index 0 is Japanese)
            description_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 32, index=0)
        except (OSError, ValueError):
            try:
                description_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 32)
            except OSError:
                description_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)

        try:
            # Try Noto Sans CJK Regular for small text (index 0 is Japanese)
            small_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 30, index=0)
        except (OSError, ValueError):
            try:
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 30)
            except OSError:
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)

        # Draw title
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (video_width - title_width) // 2
        draw.text((title_x, 200), title, fill=text_color, font=title_font)

        # Draw subtitle
        if subtitle:
            subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
            subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
            subtitle_x = (video_width - subtitle_width) // 2
            draw.text((subtitle_x, 350), subtitle, fill=text_color, font=subtitle_font)

        # Draw description
        if description:
            description_bbox = draw.textbbox((0, 0), description, font=description_font)
            description_width = description_bbox[2] - description_bbox[0]
            description_x = (video_width - description_width) // 2
            draw.text((description_x, 450), description, fill=text_color, font=description_font)

        # Draw QR codes
        if qr_urls:
            qr_size = 200
            qr_y = 550
            total_qr_width = len(qr_urls) * qr_size + (len(qr_urls) - 1) * 400
            qr_x_start = (video_width - total_qr_width) // 2

            for i, url in enumerate(qr_urls):
                qr_img = create_qr_code(url, qr_size)
                qr_x = qr_x_start + i * (qr_size + 400)
                img.paste(qr_img, (qr_x, qr_y))

                # Add label below QR code
                if qr_labels and i < len(qr_labels):
                    label = qr_labels[i]
                else:
                    label = "Artist" if i == 0 else "Venue"
                label_bbox = draw.textbbox((0, 0), label, font=small_font)
                label_width = label_bbox[2] - label_bbox[0]
                label_x = qr_x + (qr_size - label_width) // 2
                draw.text((label_x, qr_y + qr_size + 10), label, fill=text_color, font=small_font)

        return img

    # 1. Create intro slide
    logger.info("Creating intro slide...")

    # Build performer list for intro slide
    performer_list_items = []
    for entry in playlist.monthlyplaylistentry_set.order_by("position"):
        performer = entry.song.performer
        performer_text = f"{performer.name} ({performer.name_romaji})"
        if entry.is_spotlight:
            performer_text += " *SPOTLIGHTED*"
        performer_list_items.append(f"• {performer_text}")

    performer_list = "\n".join(performer_list_items)

    intro_slide = create_slide(
        title=f"HAKKO-AKKEI - {playlist.date.strftime('%B %Y')}",
        subtitle="Tokyo Live House Music Scene",
        description=performer_list,
    )
    intro_path = temp_dir / "slide_intro.png"
    intro_slide.save(intro_path)
    slides.append(intro_path)

    # 2. Create slides for each performer
    logger.info(f"Creating {playlist.monthlyplaylistentry_set.count()} performer slides...")
    for entry in playlist.monthlyplaylistentry_set.order_by("position"):
        performer = entry.song.performer

        # Get first performance for this month
        month_start = playlist.date
        if playlist.date.month == 12:  # noqa: PLR2004
            month_end = playlist.date.replace(year=playlist.date.year + 1, month=1, day=1)
        else:
            month_end = playlist.date.replace(month=playlist.date.month + 1, day=1)

        performance = (
            PerformanceSchedule.objects.filter(
                performers=performer,
                performance_date__gte=month_start,
                performance_date__lt=month_end,
            )
            .select_related("live_house", "live_house__website")
            .first()
        )

        # Prepare QR codes - always include both artist and venue
        qr_urls = []

        # Artist QR code - use website if available, otherwise use YouTube video URL
        artist_url = performer.website if performer.website else entry.song.youtube_url
        if artist_url:
            qr_urls.append(artist_url)

        # Venue QR code - use live house website if available
        if performance and hasattr(performance.live_house, "website") and performance.live_house.website.url:
            qr_urls.append(performance.live_house.website.url)

        # Create subtitle with performance info - include romaji name in parentheses
        subtitle = f"{performer.name} ({performer.name_romaji})" if performer.name_romaji else performer.name
        if performance:
            perf_date = performance.performance_date.strftime("%B %d (%a)")
            if performer.name_romaji:
                subtitle = f"{performer.name} ({performer.name_romaji})\n{perf_date} @ {performance.live_house.name}"
            else:
                subtitle = f"{performer.name}\n{perf_date} @ {performance.live_house.name}"

        # Use song title as description
        description = f'"{entry.song.title}"' if entry.song.title else ""

        # Prepare QR code labels (performer romaji name + venue name with "(venue)")
        qr_labels = []
        if qr_urls:
            qr_labels.append(performer.name_romaji if performer.name_romaji else performer.name)
            if len(qr_urls) > 1:
                venue_label = f"{performance.live_house.name} (venue)" if performance else "Venue"
                qr_labels.append(venue_label)

        performer_slide = create_slide(
            title=f"#{entry.position}",
            subtitle=subtitle,
            description=description,
            qr_urls=qr_urls if qr_urls else None,
            qr_labels=qr_labels if qr_labels else None,
        )
        performer_path = temp_dir / f"slide_performer_{entry.position:02d}.png"
        performer_slide.save(performer_path)
        slides.append(performer_path)

    # 3. Create closing slide
    logger.info("Creating closing slide...")
    closing_slide = create_slide(
        title="See You Next Month!",
        subtitle="Follow @hakkoakkei for more Live House music",
        description="Background Music: Get in the Groove – Psychedelic Grunge Instrumental - nickpanek",
        qr_urls=["https://www.youtube.com/@hakkoakkei"],
        qr_labels=["HAKKO-AKKEI YouTube"],
    )
    closing_path = temp_dir / "slide_closing.png"
    closing_slide.save(closing_path)
    slides.append(closing_path)

    # Parse introduction into sections (intro + performers + closing)
    expected_sections = 1 + playlist.monthlyplaylistentry_set.count() + 1  # intro + performers + closing
    sections = parse_introduction_sections(result_introduction, expected_sections)

    # Generate TTS using model
    logger.info(f"Generating TTS with model: {settings.VIDEO_TTS_MODEL}")
    tokens_path = temp_dir / "orpheus_tokens.txt"

    # Generate TTS audio per section if sections were successfully parsed
    use_sectioned_audio = len(sections) == expected_sections
    if use_sectioned_audio:
        logger.info(f"Generating TTS audio for {len(sections)} sections separately...")
    else:
        logger.info("Using single continuous audio (section parsing failed or disabled)")

    # Orpheus token generation (still uses full text)
    try:
        prompt = f"<|{settings.VIDEO_TTS_VOICE}|>{result_introduction}<|eot_id|>"
        response = ollama.generate(
            model=settings.VIDEO_TTS_MODEL,
            prompt=prompt,
            options={
                "temperature": settings.VIDEO_TTS_TEMPERATURE,
                "top_p": settings.VIDEO_TTS_TOP_P,
                "repetition_penalty": settings.VIDEO_TTS_REPETITION_PENALTY,
                "num_predict": 2048,
            },
        )

        with tokens_path.open("w") as f:
            if isinstance(response, dict) and "response" in response:
                f.write(response["response"])
            else:
                f.write(str(response))

        logger.info(f"Orpheus TTS tokens generated and saved to: {tokens_path}")
        logger.info("Note: Orpheus tokens saved. Use gguf_orpheus.py or Orpheus-FastAPI to convert to audio.")

    except Exception:  # noqa: BLE001
        logger.exception("Orpheus TTS generation failed, will use edge-tts fallback")

    # Generate audio using edge-tts
    logger.info(
        f"Generating audio with edge-tts ({settings.EDGE_TTS_VOICE}, "
        f"rate: {settings.EDGE_TTS_RATE}, pitch: {settings.EDGE_TTS_PITCH})..."
    )

    async def generate_tts_audio(text: str, output_path: Path) -> None:
        """Generate TTS audio using edge-tts with voice modulation."""
        communicate = edge_tts.Communicate(
            text,
            settings.EDGE_TTS_VOICE,
            rate=settings.EDGE_TTS_RATE,
            pitch=settings.EDGE_TTS_PITCH,
        )
        await communicate.save(str(output_path))

    # Audio files for each section
    audio_files = []
    slide_durations = []

    try:
        if use_sectioned_audio:
            # Generate audio for each section separately
            for idx, section in enumerate(sections):
                section_audio_path = temp_dir / f"audio_section_{idx:02d}.mp3"
                asyncio.run(generate_tts_audio(section["text"], section_audio_path))
                logger.info(f"Generated audio for section {idx + 1}/{len(sections)}: {section['type']}")

                # Apply robotic effects
                apply_robotic_effects_to_audio(section_audio_path)

                # Store audio file and calculate duration
                audio_files.append(section_audio_path)

                # Get audio duration for slide timing
                audio_segment = AudioSegment.from_mp3(str(section_audio_path))
                duration_seconds = len(audio_segment) / 1000.0  # Convert ms to seconds
                slide_durations.append(duration_seconds)

            logger.info(f"Generated {len(audio_files)} audio sections with durations: {slide_durations}")

        else:
            # Fall back to single continuous audio
            audio_path = temp_dir / "narration.mp3"
            asyncio.run(generate_tts_audio(result_introduction, audio_path))
            logger.info(f"Audio generated successfully: {audio_path}")

            # Apply robotic effects
            logger.info(
                f"Applying robotic effects (static: {settings.EDGE_TTS_STATIC_LEVEL}dB, "
                f"rate: {settings.EDGE_TTS_SAMPLE_RATE}Hz, bitrate: {settings.EDGE_TTS_BITRATE})..."
            )
            apply_robotic_effects_to_audio(audio_path)
            logger.info("Robotic effects applied successfully")

            audio_files = [audio_path]
            slide_durations = [slide_duration] * len(slides)

    except Exception:  # noqa: BLE001
        logger.exception("TTS audio generation failed, using silent audio")
        # Create silent audio as fallback
        use_sectioned_audio = False
        audio_files = []
        slide_durations = [slide_duration] * len(slides)

    # Create video from slides with appropriate durations
    logger.info("Creating video from slides...")
    video_clips = []

    if use_sectioned_audio and len(audio_files) == len(slides):
        # Create video with per-slide audio
        for idx, (slide_path, section_audio_path, duration) in enumerate(
            zip(slides, audio_files, slide_durations, strict=False)
        ):
            # Create visual clip
            clip = ImageClip(str(slide_path)).with_duration(duration)

            # Add audio to clip
            try:
                audio_clip = AudioFileClip(str(section_audio_path))
                clip = clip.with_audio(audio_clip)
            except Exception:  # noqa: BLE001
                logger.exception(f"Failed to add audio to slide {idx}")

            video_clips.append(clip)

            # Add glitch transition between slides (except after last slide)
            if idx < len(slides) - 1:
                glitch_duration = 0.1  # 100ms glitch
                glitch_clip = create_glitch_transition(slide_path, duration=glitch_duration)
                video_clips.append(glitch_clip)

        logger.info(f"Created {len(video_clips)} video clips with individual audio tracks and glitch transitions")

    else:
        # Create video with equal duration slides and single audio track
        for idx, slide_path in enumerate(slides):
            clip = ImageClip(str(slide_path)).with_duration(slide_duration)
            video_clips.append(clip)

            # Add glitch transition between slides (except after last slide)
            if idx < len(slides) - 1:
                glitch_duration = 0.1  # 100ms glitch
                glitch_clip = create_glitch_transition(slide_path, duration=glitch_duration)
                video_clips.append(glitch_clip)

        logger.info(f"Created {len(video_clips)} video clips with fixed duration and glitch transitions")

    # Concatenate all slides
    final_video = concatenate_videoclips(video_clips, method="compose")

    # Add single audio track if not using per-section audio
    if not use_sectioned_audio and audio_files:
        try:
            audio = AudioFileClip(str(audio_files[0]))
            # Trim or loop audio to match video duration
            if audio.duration > final_video.duration:
                audio = audio.subclipped(0, final_video.duration)
            elif audio.duration < final_video.duration:
                loops_needed = int(final_video.duration / audio.duration) + 1
                audio = concatenate_audioclips([audio] * loops_needed).subclipped(0, final_video.duration)

            final_video = final_video.with_audio(audio)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to add audio to video")

    # Add background music if available
    background_music_path = (
        Path(settings.BASE_DIR) / "data" / "get-in-the-groove-psychedelic-grunge-instrumental-391304.mp3"
    )
    if background_music_path.exists() and final_video.audio is not None:
        try:
            logger.info(f"Adding background music: {background_music_path}")

            # Load background music
            background_music = AudioFileClip(str(background_music_path))

            # Loop or trim background music to match video duration
            if background_music.duration < final_video.duration:
                # Loop the background music
                loops_needed = int(final_video.duration / background_music.duration) + 1
                background_music = concatenate_audioclips([background_music] * loops_needed)

            # Trim to exact video duration
            background_music = background_music.subclipped(0, final_video.duration)

            # Reduce volume to 9% of original (so speech is more prominent)
            # MoviePy 2.x: use with_volume_scaled()
            background_music = background_music.with_volume_scaled(0.09)

            # Add fade-out effect (last 3 seconds)
            fade_duration = 3.0  # seconds
            background_music = background_music.with_effects([afx.AudioFadeOut(fade_duration)])

            # Mix background music with existing audio
            mixed_audio = CompositeAudioClip([final_video.audio, background_music])
            final_video = final_video.with_audio(mixed_audio)

            logger.info("Background music added successfully with fade-out")

        except Exception:  # noqa: BLE001
            logger.exception("Failed to add background music, continuing without it")

    # Save final video
    video_dir = Path(settings.BASE_DIR) / "data" / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)

    timestamp = playlist.date.strftime("%Y%m")
    video_filename = f"playlist_intro_{timestamp}.mp4"
    video_filepath = video_dir / video_filename

    logger.info(f"Rendering final video to {video_filepath}...")
    final_video.write_videofile(
        str(video_filepath),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(temp_dir / "temp_audio.m4a"),
        remove_temp=True,
    )

    logger.info(f"Video generation complete: {video_filepath}")
    return video_filepath


def generate_weekly_playlist_introduction_text(playlist: "WeeklyPlaylist") -> tuple[str, list]:  # noqa: F821
    """Generate introduction text for a weekly playlist using AI."""
    from .models import WeeklyPlaylistEntry  # noqa: PLC0415

    playlist_intro_prompt_filepath = APP_TEMPLATE_DIR / "PLAYLIST_INTRO_PROMPT.md"
    assert playlist_intro_prompt_filepath.exists(), f"not found: {playlist_intro_prompt_filepath.resolve()}"
    playlist_intro_prompt = playlist_intro_prompt_filepath.read_text(encoding="utf8")

    messages = [
        {"role": "system", "content": playlist_intro_prompt},
    ]

    # Get the number of WeeklyPlaylistEntry items for each performer in other playlists
    # Returns dict: {performer_id: count, ...}
    performer_playlist_appearances = dict(
        WeeklyPlaylistEntry.objects.exclude(playlist=playlist)
        .values("song__performer")
        .annotate(count=Count("id"))
        .values_list("song__performer", "count")
    )

    # Calculate week boundaries
    week_start = playlist.date
    week_end = week_start + timezone.timedelta(days=7)

    # prepare playlist data:
    user_query = [
        f"For the week of {playlist.date.strftime('%Y-%m-%d')} write an introduction to selected artists "
        "below, describing where and when they will play."
        "ALWAYS mention the date and day of the week when introduction where/when the artists play."
        "The site's description is as follows (DO NOT INCLUDE it in the result response, but consider it for flavor):\n"
        "Can't see the artist for your seat? Ditch the arenas and stadiums.\n"
        'Your new favorite band is playing in dark cramped basement bars, or "Live Houses".\n'
        'We\'ll help you find your way into the current Tokyo "Live House" scene, '
        "by spotlighting the lesser known bands playing in venues where you can "
        'actually "see" the artists.  '
        "We keep it intimate by only bringing you artists performing at low capacity venues!\n\n"
        "The text generated here is for a slide presentation voice-over.\n"
        "Clearly separate the START/EACH PERFORMER/END text, so they can be "
        "properly applied to the appropriate slide.\n"
        "Selected Artists/Performers (appear in the order they appear in the playlist):\n"
    ]

    playlist_entry_data = []
    for entry in playlist.weeklyplaylistentry_set.order_by("position"):
        entry_data = [
            f"{entry.position}. Artist: {entry.song.performer.name}\n",
            f"\t- name kana: {entry.song.performer.name_kana}\n",
            f"\t- name romaji: {entry.song.performer.name_romaji}\n",
            f"\t- website: {entry.song.performer.website}\n",
            f"\t- email: {entry.song.performer.email}\n",
            f"\t- song (youtube link title): {entry.song.title}\n",
            f"\t- youtube release date: {entry.song.release_date}\n",
            f"\t- playlist appearances: {performer_playlist_appearances.get(entry.song.performer.id, 0)}\n",
        ]
        if entry.song.performer.name_romaji:
            entry_data.append(
                f"\t- email: {entry.song.performer.name_romaji}\n",
            )

        if entry.is_spotlight:
            entry_data.append(
                "Weekly Spotlight Artist: True (This performer is a special spotlighted artist for this week!)"
            )

        for social in PerformerSocialLink.objects.filter(performer=entry.song.performer):
            entry_data.append(f"\t- {social.platform}: {social.url}\n")

        # Add performance schedule details for this week
        performances = (
            PerformanceSchedule.objects.filter(
                performers=entry.song.performer,
                performance_date__gte=week_start,
                performance_date__lt=week_end,
            )
            .select_related("live_house")
            .order_by("performance_date")
        )

        if performances.exists():
            entry_data.append(f"\t- performances in week of {playlist.date.strftime('%Y-%m-%d')}:\n")
            for perf in performances:
                entry_data.append(f"\t\t- date: {perf.performance_date.strftime('%Y-%m-%d (%a)')}\n")
                entry_data.append(f"\t\t  venue: {perf.live_house.name}\n")
                entry_data.append(f"\t\t  venue kana: {perf.live_house.name_kana}\n")
                entry_data.append(f"\t\t  venue romaji: {perf.live_house.name_romaji}\n")
                entry_data.append(f"\t\t  open: {perf.open_time.strftime('%H:%M') if perf.open_time else 'TBA'}\n")
                entry_data.append(f"\t\t  start: {perf.start_time.strftime('%H:%M') if perf.start_time else 'TBA'}\n")

        entry_data.append("\n")

        playlist_entry_data.extend(entry_data)
    user_query.extend(playlist_entry_data)
    messages.append({"role": "user", "content": "".join(user_query)})

    try:
        # Call Ollama API
        response = ollama.chat(model=settings.PLAYLIST_INTRO_TEXT_GENERATION_MODEL, messages=messages)
        # Extract the feedback text from the response
        result_introduction = response["message"]["content"]

    except ollama.ResponseError as e:
        logger.exception("Ollama API error occurred")
        http_not_found = 404
        if e.status_code == http_not_found:
            error_msg = (
                f"Model '{settings.PLAYLIST_INTRO_TEXT_GENERATION_MODEL}' not found. "
                f"Please run: ollama pull hf.co/mmnga/{settings.PLAYLIST_INTRO_TEXT_GENERATION_MODEL}"
            )
        else:
            error_msg = f"Ollama API error: {e.error}"
        logger.exception(error_msg)
        raise

    return result_introduction, playlist_entry_data


def generate_weekly_playlist_video(playlist: "WeeklyPlaylist", intro_text: str | None = None) -> Path:  # noqa: C901, PLR0915, PLR0912, F821
    """
    Generate a video for the weekly playlist with QR codes, slides, and TTS narration.

    Args:
        playlist: WeeklyPlaylist object to generate video for
        intro_text: Optional pre-written introduction text. If not provided, text will be generated using AI.
    """
    # Generate or use provided introduction text
    if intro_text:
        result_introduction = intro_text
        playlist_entry_data = []  # Not needed when using custom intro text
    else:
        result_introduction, playlist_entry_data = generate_weekly_playlist_introduction_text(playlist)

    # Create temp directory for assets
    temp_dir = Path(tempfile.mkdtemp())
    logger.info(f"Created temp directory: {temp_dir}")

    # Video settings
    video_width = 1920
    video_height = 1080
    slide_duration = 8  # seconds per slide
    bg_color = (20, 20, 30)  # Dark blue background
    text_color = (255, 255, 255)  # White text

    slides = []

    # Load background image
    background_image_path = Path(settings.BASE_DIR).parent / "static" / "hakkoake_slide_background_202511.png"
    background_image = None
    if background_image_path.exists():
        try:
            background_image = Image.open(background_image_path).convert("RGBA")
            # Resize to match video dimensions
            background_image = background_image.resize((video_width, video_height), Image.Resampling.LANCZOS)
            # Set 20% transparency (80% opacity = alpha 204)
            alpha = background_image.split()[3]  # Get alpha channel
            alpha = alpha.point(lambda p: int(p * 0.8))  # 80% opacity
            background_image.putalpha(alpha)
            logger.info(f"Loaded background image: {background_image_path}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to load background image: {e}")
            background_image = None
    else:
        logger.warning(f"Background image not found: {background_image_path}")

    # Helper function to create QR code
    def create_qr_code(url: str, size: int = 200) -> Image.Image:
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").resize((size, size))

    # Helper function to create slide
    def create_slide(  # noqa: C901, PLR0912, PLR0915
        title: str,
        subtitle: str = "",
        description: str = "",
        qr_urls: list[str] | None = None,
        qr_labels: list[str] | None = None,
    ) -> Image.Image:
        # Create base image with solid background color
        img = Image.new("RGB", (video_width, video_height), bg_color)

        # Apply background image if available (with 20% transparency)
        if background_image:
            # Convert to RGBA for compositing
            img = img.convert("RGBA")
            # Composite background image onto base
            img = Image.alpha_composite(img, background_image)
            # Convert back to RGB
            img = img.convert("RGB")

        draw = ImageDraw.Draw(img)

        # Try to load fonts that support Japanese characters
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 80, index=0)
        except (OSError, ValueError):
            try:
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 80)
            except OSError:
                title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)

        try:
            subtitle_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 40, index=0)
        except (OSError, ValueError):
            try:
                subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 40)
            except OSError:
                subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)

        try:
            description_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 32, index=0)
        except (OSError, ValueError):
            try:
                description_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 32)
            except OSError:
                description_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)

        try:
            small_font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 30, index=0)
        except (OSError, ValueError):
            try:
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 30)
            except OSError:
                small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)

        # Draw title
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (video_width - title_width) // 2
        draw.text((title_x, 200), title, fill=text_color, font=title_font)

        # Draw subtitle
        if subtitle:
            subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
            subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
            subtitle_x = (video_width - subtitle_width) // 2
            draw.text((subtitle_x, 350), subtitle, fill=text_color, font=subtitle_font)

        # Draw description
        if description:
            description_bbox = draw.textbbox((0, 0), description, font=description_font)
            description_width = description_bbox[2] - description_bbox[0]
            description_x = (video_width - description_width) // 2
            draw.text((description_x, 450), description, fill=text_color, font=description_font)

        # Draw QR codes
        if qr_urls:
            qr_size = 200
            qr_y = 550
            total_qr_width = len(qr_urls) * qr_size + (len(qr_urls) - 1) * 400
            qr_x_start = (video_width - total_qr_width) // 2

            for i, url in enumerate(qr_urls):
                qr_img = create_qr_code(url, qr_size)
                qr_x = qr_x_start + i * (qr_size + 400)
                img.paste(qr_img, (qr_x, qr_y))

                # Add label below QR code
                if qr_labels and i < len(qr_labels):
                    label = qr_labels[i]
                else:
                    label = "Artist" if i == 0 else "Venue"
                label_bbox = draw.textbbox((0, 0), label, font=small_font)
                label_width = label_bbox[2] - label_bbox[0]
                label_x = qr_x + (qr_size - label_width) // 2
                draw.text((label_x, qr_y + qr_size + 10), label, fill=text_color, font=small_font)

        return img

    # Calculate week boundaries
    week_start = playlist.date
    week_end = week_start + timezone.timedelta(days=7)

    # 1. Create intro slide
    logger.info("Creating intro slide...")

    # Build performer list for intro slide
    performer_list_items = []
    for entry in playlist.weeklyplaylistentry_set.order_by("position"):
        performer = entry.song.performer
        performer_text = f"{performer.name} ({performer.name_romaji})"
        if entry.is_spotlight:
            performer_text += " *SPOTLIGHTED*"
        performer_list_items.append(f"- {performer_text}")

    performer_list = "\n".join(performer_list_items)

    intro_slide = create_slide(
        title=f"HAKKO-AKKEI - Week of {playlist.date.strftime('%Y-%m-%d')}",
        subtitle="Tokyo Live House Music Scene",
        description=performer_list,
    )
    intro_path = temp_dir / "slide_intro.png"
    intro_slide.save(intro_path)
    slides.append(intro_path)

    # 2. Create slides for each performer
    logger.info(f"Creating {playlist.weeklyplaylistentry_set.count()} performer slides...")
    for entry in playlist.weeklyplaylistentry_set.order_by("position"):
        performer = entry.song.performer

        # Get first performance for this week
        performance = (
            PerformanceSchedule.objects.filter(
                performers=performer,
                performance_date__gte=week_start,
                performance_date__lt=week_end,
            )
            .select_related("live_house", "live_house__website")
            .first()
        )

        # Prepare QR codes
        qr_urls = []

        # Artist QR code
        artist_url = performer.website if performer.website else entry.song.youtube_url
        if artist_url:
            qr_urls.append(artist_url)

        # Venue QR code
        if performance and hasattr(performance.live_house, "website") and performance.live_house.website.url:
            qr_urls.append(performance.live_house.website.url)

        # Create subtitle with performance info
        subtitle = f"{performer.name} ({performer.name_romaji})" if performer.name_romaji else performer.name
        if performance:
            perf_date = performance.performance_date.strftime("%B %d (%a)")
            if performer.name_romaji:
                subtitle = f"{performer.name} ({performer.name_romaji})\n{perf_date} @ {performance.live_house.name}"
            else:
                subtitle = f"{performer.name}\n{perf_date} @ {performance.live_house.name}"

        description = f'"{entry.song.title}"' if entry.song.title else ""

        qr_labels = []
        if qr_urls:
            qr_labels.append(performer.name_romaji if performer.name_romaji else performer.name)
            if len(qr_urls) > 1:
                venue_label = f"{performance.live_house.name} (venue)" if performance else "Venue"
                qr_labels.append(venue_label)

        performer_slide = create_slide(
            title=f"#{entry.position}",
            subtitle=subtitle,
            description=description,
            qr_urls=qr_urls if qr_urls else None,
            qr_labels=qr_labels if qr_labels else None,
        )
        performer_path = temp_dir / f"slide_performer_{entry.position:02d}.png"
        performer_slide.save(performer_path)
        slides.append(performer_path)

    # 3. Create closing slide
    logger.info("Creating closing slide...")
    closing_slide = create_slide(
        title="See You Next Week!",
        subtitle="Follow @hakkoakkei for more Live House music",
        description="Background Music: Get in the Groove – Psychedelic Grunge Instrumental - nickpanek",
        qr_urls=["https://www.youtube.com/@hakkoakkei"],
        qr_labels=["HAKKO-AKKEI YouTube"],
    )
    closing_path = temp_dir / "slide_closing.png"
    closing_slide.save(closing_path)
    slides.append(closing_path)

    # Parse introduction into sections
    expected_sections = 1 + playlist.weeklyplaylistentry_set.count() + 1
    sections = parse_introduction_sections(result_introduction, expected_sections)

    # Generate TTS using model
    logger.info(f"Generating TTS with model: {settings.VIDEO_TTS_MODEL}")
    tokens_path = temp_dir / "orpheus_tokens.txt"

    use_sectioned_audio = len(sections) == expected_sections
    if use_sectioned_audio:
        logger.info(f"Generating TTS audio for {len(sections)} sections separately...")
    else:
        logger.info("Using single continuous audio (section parsing failed or disabled)")

    # Orpheus token generation
    try:
        prompt = f"<|{settings.VIDEO_TTS_VOICE}|>{result_introduction}<|eot_id|>"
        response = ollama.generate(
            model=settings.VIDEO_TTS_MODEL,
            prompt=prompt,
            options={
                "temperature": settings.VIDEO_TTS_TEMPERATURE,
                "top_p": settings.VIDEO_TTS_TOP_P,
                "repetition_penalty": settings.VIDEO_TTS_REPETITION_PENALTY,
                "num_predict": 2048,
            },
        )

        with tokens_path.open("w") as f:
            if isinstance(response, dict) and "response" in response:
                f.write(response["response"])
            else:
                f.write(str(response))

        logger.info(f"Orpheus TTS tokens generated and saved to: {tokens_path}")

    except Exception:  # noqa: BLE001
        logger.exception("Orpheus TTS generation failed, will use edge-tts fallback")

    # Generate audio using edge-tts
    logger.info(
        f"Generating audio with edge-tts ({settings.EDGE_TTS_VOICE}, "
        f"rate: {settings.EDGE_TTS_RATE}, pitch: {settings.EDGE_TTS_PITCH})..."
    )

    async def generate_tts_audio(text: str, output_path: Path) -> None:
        communicate = edge_tts.Communicate(
            text,
            settings.EDGE_TTS_VOICE,
            rate=settings.EDGE_TTS_RATE,
            pitch=settings.EDGE_TTS_PITCH,
        )
        await communicate.save(str(output_path))

    audio_files = []
    slide_durations = []

    try:
        if use_sectioned_audio:
            for idx, section in enumerate(sections):
                section_audio_path = temp_dir / f"audio_section_{idx:02d}.mp3"
                asyncio.run(generate_tts_audio(section["text"], section_audio_path))
                logger.info(f"Generated audio for section {idx + 1}/{len(sections)}: {section['type']}")

                apply_robotic_effects_to_audio(section_audio_path)

                audio_files.append(section_audio_path)

                audio_segment = AudioSegment.from_mp3(str(section_audio_path))
                duration_seconds = len(audio_segment) / 1000.0
                slide_durations.append(duration_seconds)

            logger.info(f"Generated {len(audio_files)} audio sections with durations: {slide_durations}")

        else:
            audio_path = temp_dir / "narration.mp3"
            asyncio.run(generate_tts_audio(result_introduction, audio_path))
            logger.info(f"Audio generated successfully: {audio_path}")

            logger.info(
                f"Applying robotic effects (static: {settings.EDGE_TTS_STATIC_LEVEL}dB, "
                f"rate: {settings.EDGE_TTS_SAMPLE_RATE}Hz, bitrate: {settings.EDGE_TTS_BITRATE})..."
            )
            apply_robotic_effects_to_audio(audio_path)
            logger.info("Robotic effects applied successfully")

            audio_files = [audio_path]
            slide_durations = [slide_duration] * len(slides)

    except Exception:  # noqa: BLE001
        logger.exception("TTS audio generation failed, using silent audio")
        use_sectioned_audio = False
        audio_files = []
        slide_durations = [slide_duration] * len(slides)

    # Create video from slides
    logger.info("Creating video from slides...")
    video_clips = []

    if use_sectioned_audio and len(audio_files) == len(slides):
        for idx, (slide_path, section_audio_path, duration) in enumerate(
            zip(slides, audio_files, slide_durations, strict=False)
        ):
            clip = ImageClip(str(slide_path)).with_duration(duration)

            try:
                audio_clip = AudioFileClip(str(section_audio_path))
                clip = clip.with_audio(audio_clip)
            except Exception:  # noqa: BLE001
                logger.exception(f"Failed to add audio to slide {idx}")

            video_clips.append(clip)

            if idx < len(slides) - 1:
                glitch_duration = 0.1
                glitch_clip = create_glitch_transition(slide_path, duration=glitch_duration)
                video_clips.append(glitch_clip)

        logger.info(f"Created {len(video_clips)} video clips with individual audio tracks and glitch transitions")

    else:
        for idx, slide_path in enumerate(slides):
            clip = ImageClip(str(slide_path)).with_duration(slide_duration)
            video_clips.append(clip)

            if idx < len(slides) - 1:
                glitch_duration = 0.1
                glitch_clip = create_glitch_transition(slide_path, duration=glitch_duration)
                video_clips.append(glitch_clip)

        logger.info(f"Created {len(video_clips)} video clips with fixed duration and glitch transitions")

    final_video = concatenate_videoclips(video_clips, method="compose")

    if not use_sectioned_audio and audio_files:
        try:
            audio = AudioFileClip(str(audio_files[0]))
            if audio.duration > final_video.duration:
                audio = audio.subclipped(0, final_video.duration)
            elif audio.duration < final_video.duration:
                loops_needed = int(final_video.duration / audio.duration) + 1
                audio = concatenate_audioclips([audio] * loops_needed).subclipped(0, final_video.duration)

            final_video = final_video.with_audio(audio)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to add audio to video")

    # Add background music if available
    background_music_path = (
        Path(settings.BASE_DIR) / "data" / "get-in-the-groove-psychedelic-grunge-instrumental-391304.mp3"
    )
    if background_music_path.exists() and final_video.audio is not None:
        try:
            logger.info(f"Adding background music: {background_music_path}")

            background_music = AudioFileClip(str(background_music_path))

            if background_music.duration < final_video.duration:
                loops_needed = int(final_video.duration / background_music.duration) + 1
                background_music = concatenate_audioclips([background_music] * loops_needed)

            background_music = background_music.subclipped(0, final_video.duration)
            background_music = background_music.with_volume_scaled(0.09)

            fade_duration = 3.0
            background_music = background_music.with_effects([afx.AudioFadeOut(fade_duration)])

            mixed_audio = CompositeAudioClip([final_video.audio, background_music])
            final_video = final_video.with_audio(mixed_audio)

            logger.info("Background music added successfully with fade-out")

        except Exception:  # noqa: BLE001
            logger.exception("Failed to add background music, continuing without it")

    # Save final video
    video_dir = Path(settings.BASE_DIR) / "data" / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)

    timestamp = playlist.date.strftime("%Y%m%d")
    video_filename = f"playlist_intro_week_{timestamp}.mp4"
    video_filepath = video_dir / video_filename

    logger.info(f"Rendering final video to {video_filepath}...")
    final_video.write_videofile(
        str(video_filepath),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(temp_dir / "temp_audio.m4a"),
        remove_temp=True,
    )

    logger.info(f"Video generation complete: {video_filepath}")
    return video_filepath
