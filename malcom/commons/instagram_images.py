"""Styled image generation for Instagram playlist posts.

Generates two types of images:
- Playlist cover: numbered artist list with hakoake branding
- Performer card: performer photo/art + event details overlay
- QR code slide: QR code + metadata overlay for Instagram carousel
"""

from __future__ import annotations

import io
import logging
from datetime import date  # noqa: TC003
from pathlib import Path
from typing import TYPE_CHECKING

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

if TYPE_CHECKING:
    from houses.models import PerformanceSchedule
    from performers.models import Performer

logger = logging.getLogger(__name__)

# --- Canvas ---
IMG_W = 1080
IMG_H = 1080

# --- Colour palette (matches intro video style) ---
BG_COLOR = (20, 20, 30)
OVERLAY_COLOR = (20, 20, 30, 200)  # semi-transparent dark overlay for text legibility
TEXT_COLOR = (255, 255, 255)
ACCENT_COLOR = (255, 100, 100)  # coral — titles / highlights
SECONDARY_COLOR = (200, 200, 200)
DIM_COLOR = (150, 150, 150)
DIVIDER_COLOR = (60, 60, 80)

# --- Font paths ---
_FONT_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
_FONT_REGULAR = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

# --- Fallback background image (used when no performer/flyer image is available) ---
_FALLBACK_BG = Path(__file__).resolve().parent.parent.parent / "insta-background.png"

INSTAGRAM_HASHTAGS = (
    "hakoake",
    "tokyo",
    "livemusic",
    "livehouse",
    "japanmusic",
    "tokyomusic",
    "ライブ",
    "東京",
    "ライブハウス",
    "音楽",
    "バンド",
    "日本音楽",
    "tokyolivemusic",
    "インディーズ",
    "jrock",
)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = _FONT_BOLD if bold else _FONT_REGULAR
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _text_wrapped(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Split text into lines that fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _to_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _load_performer_image(performer: Performer) -> Image.Image | None:
    """Load the best available performer image (performer_image → fanart → banner)."""
    for field in ("performer_image", "fanart_image", "banner_image", "logo_image"):
        field_val = getattr(performer, field, None)
        if field_val and field_val.name:
            try:
                path = Path(field_val.path)
                if path.exists():
                    return Image.open(path).convert("RGB")
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Could not load {field} for {performer.name}: {exc}")
    return None


def _fill_background(_img: Image.Image, source: Image.Image | None) -> Image.Image:
    """Fill canvas with source image (blurred, darkened) or fallback background at 60% opacity."""
    if source:
        # Scale to fill, blur, then darken
        ratio = max(IMG_W / source.width, IMG_H / source.height)
        new_w = int(source.width * ratio)
        new_h = int(source.height * ratio)
        resized = source.resize((new_w, new_h), Image.Resampling.LANCZOS)
        x = (new_w - IMG_W) // 2
        y = (new_h - IMG_H) // 2
        cropped = resized.crop((x, y, x + IMG_W, y + IMG_H))
        blurred = cropped.filter(ImageFilter.GaussianBlur(radius=8))
        # Dark overlay
        overlay = Image.new("RGBA", (IMG_W, IMG_H), OVERLAY_COLOR)
        base = blurred.convert("RGBA")
        base.alpha_composite(overlay)
        return base.convert("RGB")
    # No performer/flyer image — composite fallback background at 60% opacity over dark base
    base = Image.new("RGB", (IMG_W, IMG_H), BG_COLOR).convert("RGBA")
    if _FALLBACK_BG.exists():
        try:
            bg = Image.open(_FALLBACK_BG).convert("RGBA")
            ratio = max(IMG_W / bg.width, IMG_H / bg.height)
            new_w = int(bg.width * ratio)
            new_h = int(bg.height * ratio)
            bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
            x = (new_w - IMG_W) // 2
            y = (new_h - IMG_H) // 2
            bg = bg.crop((x, y, x + IMG_W, y + IMG_H))
            r, g, b, a = bg.split()
            a = a.point(lambda v: int(v * 0.6))  # 60% opacity
            bg = Image.merge("RGBA", (r, g, b, a))
            base.alpha_composite(bg)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Could not load fallback background {_FALLBACK_BG}: {exc}")
    return base.convert("RGB")


def generate_playlist_cover(
    _title: str,
    week_label: str,
    entries: list[tuple[int, str]],  # [(position, performer_name), ...]
) -> bytes:
    """Generate a numbered artist list cover image. Returns JPEG bytes.

    Args:
        _title: Playlist title (reserved for future use)
        week_label: Human-readable period (e.g. "Week of 2026-03-30")
        entries: List of (position, performer_name) tuples in playlist order
    """
    img = Image.new("RGB", (IMG_W, IMG_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- Top accent bar ---
    draw.rectangle([(0, 0), (IMG_W, 8)], fill=ACCENT_COLOR)

    # --- Branding ---
    font_brand = _font(52, bold=True)
    draw.text((IMG_W // 2, 60), "HAKKO-AKKEI", font=font_brand, fill=ACCENT_COLOR, anchor="mt")

    # --- Week label ---
    font_week = _font(32)
    draw.text((IMG_W // 2, 130), week_label, font=font_week, fill=SECONDARY_COLOR, anchor="mt")

    # --- Divider ---
    draw.rectangle([(80, 170), (IMG_W - 80, 173)], fill=DIVIDER_COLOR)

    # --- "THIS WEEK'S LINEUP" subheader ---
    font_sub = _font(28)
    draw.text((IMG_W // 2, 195), "THIS WEEK'S LINEUP", font=font_sub, fill=DIM_COLOR, anchor="mt")

    # --- Performer list ---
    font_num = _font(34, bold=True)
    font_name = _font(38, bold=True)
    y = 250
    line_h = 72
    max_visible = 10

    for pos, name in entries[:max_visible]:
        # Position number circle
        draw.ellipse([(80, y), (80 + 44, y + 44)], fill=ACCENT_COLOR)
        draw.text((102, y + 22), str(pos), font=font_num, fill=TEXT_COLOR, anchor="mm")
        # Performer name
        draw.text((145, y + 22), name, font=font_name, fill=TEXT_COLOR, anchor="lm")
        y += line_h

    if len(entries) > max_visible:
        draw.text(
            (IMG_W // 2, y + 10),
            f"+ {len(entries) - max_visible} more",
            font=font_sub,
            fill=DIM_COLOR,
            anchor="mt",
        )

    # --- Bottom accent bar ---
    draw.rectangle([(0, IMG_H - 8), (IMG_W, IMG_H)], fill=ACCENT_COLOR)

    # --- YouTube label at bottom ---
    font_yt = _font(26)
    draw.text((IMG_W // 2, IMG_H - 40), "▶ YouTube Playlist", font=font_yt, fill=SECONDARY_COLOR, anchor="mm")

    return _to_jpeg(img)


def generate_performer_card(
    performer: Performer,
    position: int,
    schedules: list[PerformanceSchedule],
) -> bytes:
    """Generate a styled performer card with photo and event details. Returns JPEG bytes."""
    source_img = _load_performer_image(performer)
    img = _fill_background(Image.new("RGB", (IMG_W, IMG_H), BG_COLOR), source_img)
    draw = ImageDraw.Draw(img)

    # --- Top accent bar ---
    draw.rectangle([(0, 0), (IMG_W, 8)], fill=ACCENT_COLOR)

    # --- Position badge ---
    draw.ellipse([(40, 30), (40 + 60, 30 + 60)], fill=ACCENT_COLOR)
    draw.text((70, 60), str(position), font=_font(32, bold=True), fill=TEXT_COLOR, anchor="mm")

    # --- Performer name (large, near top if no image, else near bottom) ---
    name_y = 560 if source_img else 300
    font_name = _font(68, bold=True)
    # Shadow for legibility
    draw.text((IMG_W // 2 + 2, name_y + 2), performer.name, font=font_name, fill=(0, 0, 0), anchor="mt")
    draw.text((IMG_W // 2, name_y), performer.name, font=font_name, fill=TEXT_COLOR, anchor="mt")

    # Romaji / kana subtitle if different from name
    if performer.name_romaji and performer.name_romaji.lower() != performer.name.lower():
        font_romaji = _font(32)
        draw.text(
            (IMG_W // 2, name_y + 82),
            performer.name_romaji,
            font=font_romaji,
            fill=SECONDARY_COLOR,
            anchor="mt",
        )
        sched_y = name_y + 130
    else:
        sched_y = name_y + 88

    # --- Divider ---
    draw.rectangle([(80, sched_y), (IMG_W - 80, sched_y + 2)], fill=ACCENT_COLOR)
    sched_y += 16

    # --- Venue / schedule info ---
    font_venue = _font(30, bold=True)
    font_info = _font(26)
    shown = 0
    for sched in schedules[:4]:
        date_str = sched.performance_date.strftime("%Y-%m-%d (%a)")
        venue = sched.live_house.name
        draw.text((IMG_W // 2, sched_y), f"📅 {date_str}", font=font_venue, fill=ACCENT_COLOR, anchor="mt")
        sched_y += 38
        draw.text((IMG_W // 2, sched_y), f"📍 {venue}", font=font_info, fill=SECONDARY_COLOR, anchor="mt")
        sched_y += 36
        if sched.open_time or sched.start_time:
            time_parts = []
            if sched.open_time:
                time_parts.append(f"OPEN {sched.open_time.strftime('%H:%M')}")
            if sched.start_time:
                time_parts.append(f"START {sched.start_time.strftime('%H:%M')}")
            draw.text(
                (IMG_W // 2, sched_y),
                "  ".join(time_parts),
                font=font_info,
                fill=DIM_COLOR,
                anchor="mt",
            )
            sched_y += 34
        sched_y += 8
        shown += 1

    if not shown:
        draw.text((IMG_W // 2, sched_y), "Tokyo Live Houses", font=font_info, fill=DIM_COLOR, anchor="mt")

    # --- Bottom accent bar ---
    draw.rectangle([(0, IMG_H - 8), (IMG_W, IMG_H)], fill=ACCENT_COLOR)

    # --- HAKKO-AKKEI branding bottom-right ---
    draw.text(
        (IMG_W - 40, IMG_H - 30),
        "HAKKO-AKKEI",
        font=_font(22),
        fill=(100, 100, 120),
        anchor="rb",
    )

    return _to_jpeg(img)


def generate_qr_code(url: str, size: int = 300) -> Image.Image:
    """Generate a QR code image for the given URL."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    return qr_img.resize((size, size), Image.Resampling.LANCZOS)


def _resize_to_square(raw_bytes: bytes, size: int = 1080) -> bytes:
    """Center-crop raw image bytes to a square JPEG of the given size."""
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    w, h = img.size
    min_dim = min(w, h)
    x = (w - min_dim) // 2
    y = (h - min_dim) // 2
    cropped = img.crop((x, y, x + min_dim, y + min_dim))
    resized = cropped.resize((size, size), Image.Resampling.LANCZOS)
    return _to_jpeg(resized)


def generate_qr_slide(
    url: str,
    position: int,
    performer_name: str,
    venue_name: str,
    event_name: str,
    event_date: date,
) -> bytes:
    """Generate a 1080x1080 QR code slide with metadata overlay. Returns JPEG bytes.

    Args:
        url: QR code target URL
        position: Performer position index in the playlist
        performer_name: Performer name
        venue_name: Live house name
        event_name: PerformanceSchedule.performance_name
        event_date: PerformanceSchedule.performance_date
    """
    img = Image.new("RGB", (IMG_W, IMG_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # --- Top accent bar ---
    draw.rectangle([(0, 0), (IMG_W, 8)], fill=ACCENT_COLOR)

    # --- Branding ---
    font_brand = _font(36, bold=True)
    draw.text((IMG_W // 2, 40), "HAKKO-AKKEI", font=font_brand, fill=ACCENT_COLOR, anchor="mt")

    # --- QR code centered in upper portion ---
    qr_size = 400
    qr_img = generate_qr_code(url, qr_size)
    qr_x = (IMG_W - qr_size) // 2
    qr_y = 100
    img.paste(qr_img, (qr_x, qr_y))

    # --- Divider below QR ---
    divider_y = qr_y + qr_size + 20
    draw.rectangle([(80, divider_y), (IMG_W - 80, divider_y + 2)], fill=DIVIDER_COLOR)

    # --- Metadata text ---
    text_y = divider_y + 24

    # Position badge + performer name on same line
    badge_r = 26
    badge_cx = 80 + badge_r
    badge_cy = text_y + badge_r
    draw.ellipse(
        [(badge_cx - badge_r, badge_cy - badge_r), (badge_cx + badge_r, badge_cy + badge_r)],
        fill=ACCENT_COLOR,
    )
    draw.text((badge_cx, badge_cy), str(position), font=_font(26, bold=True), fill=TEXT_COLOR, anchor="mm")

    font_name = _font(52, bold=True)
    draw.text((80 + badge_r * 2 + 16, badge_cy), performer_name, font=font_name, fill=TEXT_COLOR, anchor="lm")
    text_y += badge_r * 2 + 16

    # Venue
    font_detail = _font(34)
    draw.text((IMG_W // 2, text_y), f"📍 {venue_name}", font=font_detail, fill=SECONDARY_COLOR, anchor="mt")
    text_y += 50

    # Event name (if set)
    if event_name:
        font_event = _font(30)
        lines = _text_wrapped(draw, event_name, font_event, IMG_W - 160)
        for line in lines[:2]:
            draw.text((IMG_W // 2, text_y), line, font=font_event, fill=DIM_COLOR, anchor="mt")
            text_y += 40

    # Event date
    font_date = _font(34, bold=True)
    draw.text(
        (IMG_W // 2, text_y),
        f"📅 {event_date.strftime('%Y-%m-%d (%a)')}",
        font=font_date,
        fill=ACCENT_COLOR,
        anchor="mt",
    )

    # --- Bottom accent bar ---
    draw.rectangle([(0, IMG_H - 8), (IMG_W, IMG_H)], fill=ACCENT_COLOR)

    # --- Scan label above bottom bar ---
    draw.text(
        (IMG_W // 2, IMG_H - 40),
        "Scan QR code for details",
        font=_font(26),
        fill=SECONDARY_COLOR,
        anchor="mm",
    )

    return _to_jpeg(img)
