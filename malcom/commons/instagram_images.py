"""Styled Instagram carousel slide generators (1080×1080 JPEG output).

Four slide types are exported, all rendered against the warm analog
Tokyo live-house aesthetic defined in commons/design.py:

- generate_playlist_cover  — numbered lineup cover slide
- generate_performer_card  — full-bleed performer photo + editorial caption
- generate_qr_slide        — QR-only slide with metadata
- generate_combined_flyer_qr_slide — flyer-as-background + QR overlay panel

The design system (palette, fonts, helpers) lives in `commons.design` and
is shared with the playlist video generator in `houses/functions.py` so the
two pipelines never drift again.
"""

from __future__ import annotations

import io
import logging
from datetime import date  # noqa: TC003
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from commons.design import (
    AGED_CREAM,
    AGED_CREAM_PANEL,
    FLYER_RED,
    INK_GRAY,
    INSTAGRAM_SQUARE,
    PAPER_BLACK,
    PAPER_BLACK_WASH,
    SP_LG,
    SP_MD,
    SP_SM,
    SP_XS,
    apply_paper_grain,
    body_font,
    build_qr_code,
    display_font,
    draw_corner_wordmark,
    draw_torn_edge,
    load_brand_background,
    scale_to_fill,
    wrap_text,
)

if TYPE_CHECKING:
    from houses.models import PerformanceSchedule
    from performers.models import Performer

logger = logging.getLogger(__name__)

# --- Canvas ---
# Kept as module-level constants for back-compat with tests and external callers.
IMG_W, IMG_H = INSTAGRAM_SQUARE

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


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Back-compat shim for the body font loader.

    Existing tests and a couple of legacy call sites import `_font` directly.
    Delegates to `commons.design.body_font` so the CJK fallback chain is
    shared with the video generator.
    """
    return body_font(size, bold=bold)


def _to_jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _load_performer_image(performer: Performer) -> Image.Image | None:
    """Load the best available performer image (performer_image → fanart → banner → logo)."""
    for field in ("performer_image", "fanart_image", "banner_image", "logo_image"):
        field_val = getattr(performer, field, None)
        if field_val and field_val.name:
            try:
                path = Path(field_val.path)
                if path.exists():
                    return Image.open(path).convert("RGB")
            except OSError as exc:
                logger.debug(f"Could not load {field} for {performer.name}: {exc}")
    return None


def _paper_black_canvas() -> Image.Image:
    """Return a fresh PAPER_BLACK canvas with paper grain applied."""
    base = Image.new("RGB", INSTAGRAM_SQUARE, PAPER_BLACK)
    return apply_paper_grain(base)


def _resize_to_square(raw_bytes: bytes, size: int = 1080) -> bytes:
    """Center-crop raw image bytes to a square JPEG of the given size."""
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    cropped = scale_to_fill(img, (size, size))
    return _to_jpeg(cropped)


def generate_qr_code(url: str, size: int = 300) -> Image.Image:
    """Back-compat shim — delegates to commons.design.build_qr_code."""
    return build_qr_code(url, size)


# --- Slide 1: playlist cover ----------------------------------------------------


def generate_playlist_cover(
    _title: str,
    week_label: str,
    entries: list[tuple[int, str]],
) -> bytes:
    """Numbered lineup cover slide.

    Layout:
      - Full-bleed brand background photo, darkened with a paper-black wash
      - Top-left editorial display label (week / month) in cream
      - Big oversized vermillion numerals down the left rail with cream names
      - Corner wordmark bottom-left

    Args:
        _title: Reserved for future use; the cover does not display a title.
        week_label: Period label, e.g. "Week of 2026-03-30" or "April 2026".
        entries: Ordered (position, performer_name) tuples in playlist order.
    """
    base = load_brand_background(INSTAGRAM_SQUARE)
    if base is None:
        canvas = _paper_black_canvas()
    else:
        canvas = base.copy().convert("RGBA")
        wash = Image.new("RGBA", INSTAGRAM_SQUARE, PAPER_BLACK_WASH)
        canvas.alpha_composite(wash)
        canvas = apply_paper_grain(canvas.convert("RGB"))

    draw = ImageDraw.Draw(canvas)

    # --- Editorial header (display font, mincho serif) ---
    label_font = body_font(22, bold=True)
    draw.text(
        (SP_LG, SP_LG),
        "TOKYO LIVE HOUSES // LINEUP",
        font=label_font,
        fill=INK_GRAY,
    )

    period_font = display_font(72)
    draw.text((SP_LG, SP_LG + 36), week_label, font=period_font, fill=AGED_CREAM)

    # --- Numbered lineup ---
    max_visible = 8
    visible = entries[:max_visible]
    list_top = 280
    list_bottom = IMG_H - 140
    available_h = list_bottom - list_top
    line_h = available_h // max(len(visible), 1)
    line_h = max(72, min(line_h, 110))

    num_font = display_font(int(line_h * 0.9))
    name_font = display_font(int(line_h * 0.55))
    name_x = SP_LG + 180

    for i, (pos, name) in enumerate(visible):
        y = list_top + i * line_h
        # Oversized vermillion numeral
        draw.text(
            (SP_LG + 4, y + line_h // 2),
            f"{pos:02d}",
            font=num_font,
            fill=FLYER_RED,
            anchor="lm",
        )
        # Performer name in cream — wrap if too long
        max_name_w = IMG_W - name_x - SP_LG
        lines = wrap_text(draw, name, name_font, max_name_w)
        if lines:
            draw.text((name_x, y + line_h // 2), lines[0], font=name_font, fill=AGED_CREAM, anchor="lm")

    if len(entries) > max_visible:
        more_font = body_font(24, bold=True)
        draw.text(
            (SP_LG, list_bottom + 8),
            f"+ {len(entries) - max_visible} more",
            font=more_font,
            fill=INK_GRAY,
            anchor="lt",
        )

    # --- Corner wordmark ---
    draw_corner_wordmark(draw, (SP_LG, IMG_H - SP_LG), anchor="lb", color=INK_GRAY, size=18)

    return _to_jpeg(canvas)


# --- Slide 2: performer card ----------------------------------------------------


def generate_performer_card(
    performer: Performer,
    position: int,
    schedules: list[PerformanceSchedule],
) -> bytes:
    """Performer card with full-saturation photo and editorial caption.

    Layout:
      - Top 62% of the canvas: performer photo (or brand bg fallback) at full
        saturation — no blur, no overlay. Photos are the point.
      - Torn-paper edge separates photo from a PAPER_BLACK caption panel.
      - Bottom 38%: display-font name + romaji + venue/date metadata
      - Oversized vermillion position numeral in the top-left corner of the panel
    """
    source_img = _load_performer_image(performer)
    photo_h = int(IMG_H * 0.62)

    # --- Photo region ---
    photo_canvas = Image.new("RGB", INSTAGRAM_SQUARE, PAPER_BLACK)
    if source_img is not None:
        photo = scale_to_fill(source_img, (IMG_W, photo_h))
    else:
        bg = load_brand_background((IMG_W, photo_h))
        photo = bg if bg is not None else Image.new("RGB", (IMG_W, photo_h), PAPER_BLACK)
    photo_canvas.paste(photo, (0, 0))

    # --- Paper black caption panel under the photo ---
    panel = Image.new("RGB", (IMG_W, IMG_H - photo_h), PAPER_BLACK)
    photo_canvas.paste(panel, (0, photo_h))

    # --- Torn edge between photo and panel ---
    draw = ImageDraw.Draw(photo_canvas)
    draw_torn_edge(draw, photo_h, IMG_W, PAPER_BLACK, amplitude=8, segments=70, seed=position * 7 + 3)

    # Apply paper grain over the whole composition
    composed = apply_paper_grain(photo_canvas)
    draw = ImageDraw.Draw(composed)

    # --- Oversized position numeral straddling the seam ---
    numeral_font = display_font(220)
    draw.text(
        (SP_LG, photo_h + 6),
        f"{position:02d}",
        font=numeral_font,
        fill=FLYER_RED,
        anchor="lm",
    )

    # --- Performer name ---
    name_x = SP_LG + 200
    text_top = photo_h + SP_LG
    name_font = display_font(64)
    name_lines = wrap_text(draw, performer.name, name_font, IMG_W - name_x - SP_LG)
    y = text_top
    for line in name_lines[:2]:
        draw.text((name_x, y), line, font=name_font, fill=AGED_CREAM, anchor="lt")
        y += 70

    # Romaji subtitle (only if it adds new info)
    if performer.name_romaji and performer.name_romaji.lower() != performer.name.lower():
        romaji_font = body_font(26)
        draw.text((name_x, y), performer.name_romaji, font=romaji_font, fill=INK_GRAY, anchor="lt")
        y += 36

    # --- Venue / date metadata ---
    y += SP_XS
    detail_font = body_font(24, bold=True)
    sub_font = body_font(22)
    rendered = 0
    for sched in schedules[:2]:
        if y > IMG_H - SP_LG:
            break
        date_str = sched.performance_date.strftime("%a %b %d")
        venue = sched.live_house.name
        draw.text((name_x, y), date_str.upper(), font=detail_font, fill=FLYER_RED, anchor="lt")
        y += 30
        draw.text((name_x, y), venue, font=sub_font, fill=AGED_CREAM, anchor="lt")
        y += 32
        rendered += 1

    if not rendered:
        draw.text((name_x, y), "TOKYO LIVE HOUSES", font=detail_font, fill=INK_GRAY, anchor="lt")

    # --- Corner wordmark bottom-right ---
    draw_corner_wordmark(
        draw,
        (IMG_W - SP_LG, IMG_H - SP_LG),
        anchor="rb",
        color=INK_GRAY,
        size=16,
    )

    return _to_jpeg(composed)


# --- Slide 3: QR-only slide -----------------------------------------------------


def generate_qr_slide(
    url: str,
    position: int,
    performer_name: str,
    venue_name: str,
    event_name: str,
    event_date: date,
) -> bytes:
    """QR slide with editorial left rail + cream QR card on the right.

    Args:
        url: QR target URL.
        position: Performer position in the playlist.
        performer_name: Performer name (display).
        venue_name: Live house name.
        event_name: PerformanceSchedule.performance_name (may be empty).
        event_date: PerformanceSchedule.performance_date.
    """
    canvas = _paper_black_canvas()
    draw = ImageDraw.Draw(canvas)

    # --- Left rail: editorial copy ---
    rail_x = SP_LG
    rail_w = int(IMG_W * 0.55)

    # SCAN label
    label_font = body_font(22, bold=True)
    draw.text((rail_x, SP_LG), "SCAN // GET TICKETS", font=label_font, fill=INK_GRAY)

    # Big position numeral
    numeral_font = display_font(180)
    draw.text((rail_x, SP_LG + 32), f"{position:02d}", font=numeral_font, fill=FLYER_RED, anchor="lt")

    # Performer name (display serif)
    name_font = display_font(58)
    name_y = SP_LG + 240
    name_lines = wrap_text(draw, performer_name, name_font, rail_w)
    for line in name_lines[:2]:
        draw.text((rail_x, name_y), line, font=name_font, fill=AGED_CREAM, anchor="lt")
        name_y += 64

    # Venue + date metadata
    meta_font = body_font(24, bold=True)
    draw.text((rail_x, name_y + SP_SM), venue_name, font=meta_font, fill=AGED_CREAM, anchor="lt")
    name_y += SP_SM + 32

    date_font = body_font(22, bold=True)
    draw.text(
        (rail_x, name_y),
        event_date.strftime("%a %b %d, %Y").upper(),
        font=date_font,
        fill=FLYER_RED,
        anchor="lt",
    )
    name_y += 30

    # Event name (optional, smaller, secondary)
    if event_name:
        event_font = body_font(20)
        for line in wrap_text(draw, event_name, event_font, rail_w)[:2]:
            draw.text((rail_x, name_y), line, font=event_font, fill=INK_GRAY, anchor="lt")
            name_y += 26

    # --- Right side: cream QR card ---
    qr_card_size = 420
    card_x = IMG_W - qr_card_size - SP_LG
    card_y = (IMG_H - qr_card_size) // 2

    # Cream panel behind QR
    card_panel = Image.new("RGBA", (qr_card_size, qr_card_size), AGED_CREAM_PANEL)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(card_panel, (card_x, card_y))
    canvas = canvas_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    # QR code centered inside the card
    qr_size = qr_card_size - 2 * SP_MD
    qr_img = generate_qr_code(url, qr_size)
    canvas.paste(qr_img, (card_x + SP_MD, card_y + SP_MD))

    # --- Corner wordmark ---
    draw_corner_wordmark(
        draw,
        (SP_LG, IMG_H - SP_LG),
        anchor="lb",
        color=INK_GRAY,
        size=16,
    )

    return _to_jpeg(canvas)


# --- Slide 4: combined flyer + QR ----------------------------------------------


def generate_combined_flyer_qr_slide(
    flyer_bytes: bytes,
    url: str,
    position: int,
    performer_name: str,
    venue_name: str,
    event_name: str,  # noqa: ARG001
    event_date: date,
) -> bytes:
    """Flyer-as-background + QR card overlay.

    The flyer fills the canvas at full saturation. A small cream QR card sits
    in the bottom-right corner with the date and venue. Position numeral
    bleeds in from the top-left corner in vermillion.
    """
    flyer_img = Image.open(io.BytesIO(flyer_bytes)).convert("RGB")
    composed = scale_to_fill(flyer_img, INSTAGRAM_SQUARE)
    composed = apply_paper_grain(composed, opacity=14)
    draw = ImageDraw.Draw(composed)

    # --- Position numeral top-left, bleeds slightly off canvas ---
    numeral_font = display_font(200)
    # Drop shadow for legibility against arbitrary flyer art
    draw.text((SP_MD + 3, SP_XS + 3), f"{position:02d}", font=numeral_font, fill=PAPER_BLACK, anchor="lt")
    draw.text((SP_MD, SP_XS), f"{position:02d}", font=numeral_font, fill=FLYER_RED, anchor="lt")

    # --- QR card (bottom-right) ---
    card_w = 380
    card_h = 380
    card_x = IMG_W - card_w - SP_LG
    card_y = IMG_H - card_h - SP_LG

    card_panel = Image.new("RGBA", (card_w, card_h), AGED_CREAM_PANEL)
    composed_rgba = composed.convert("RGBA")
    composed_rgba.alpha_composite(card_panel, (card_x, card_y))
    composed = composed_rgba.convert("RGB")
    draw = ImageDraw.Draw(composed)

    # QR code
    qr_size = 240
    qr_img = generate_qr_code(url, qr_size)
    qr_x = card_x + (card_w - qr_size) // 2
    qr_y = card_y + SP_MD
    composed.paste(qr_img, (qr_x, qr_y))

    # Caption inside the card under the QR
    cap_top = qr_y + qr_size + SP_XS
    name_font = body_font(22, bold=True)
    venue_font = body_font(18)
    date_font = body_font(20, bold=True)

    # Performer name (truncated to fit)
    name_lines = wrap_text(draw, performer_name, name_font, card_w - 2 * SP_MD)
    name_text = name_lines[0] if name_lines else performer_name
    draw.text((card_x + card_w // 2, cap_top), name_text, font=name_font, fill=PAPER_BLACK, anchor="mt")
    cap_top += 26

    draw.text(
        (card_x + card_w // 2, cap_top),
        venue_name,
        font=venue_font,
        fill=INK_GRAY,
        anchor="mt",
    )
    cap_top += 22

    draw.text(
        (card_x + card_w // 2, cap_top),
        event_date.strftime("%a %b %d").upper(),
        font=date_font,
        fill=FLYER_RED,
        anchor="mt",
    )

    # --- Corner wordmark top-right (unobtrusive) ---
    # Position numeral owns top-left, QR card owns bottom-right.
    draw_corner_wordmark(draw, (IMG_W - SP_MD, SP_MD), anchor="rt", color=AGED_CREAM, size=14)

    return _to_jpeg(composed)
