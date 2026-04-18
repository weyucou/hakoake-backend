"""Hakoake design system — single source of truth for colors, fonts, and layout helpers.

The visual language is Tokyo live-house flyer wall: warm analog darkness,
aged-paper cream, and a single oxidized-vermillion shock color. Display type
is Shippori Mincho B1 Bold (Japanese editorial serif, committed under
commons/fonts/). Body type stays Noto Sans CJK JP.

All Instagram carousel slide generators (commons/instagram_images.py) and the
YouTube playlist video slide generator (houses/functions.py::_generate_playlist_video)
import constants and helpers from this module. Drift between those two pipelines
used to be a real problem — keep new constants here, not in either caller.
"""

from __future__ import annotations

import functools
import logging
import random
from pathlib import Path

import numpy as np
import qrcode
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# --- Palette ---
# Warm analog darkness pulled from the brand background photograph
# (static/hakkoake_slide_background_202511.png — basement flyer wall).
PAPER_BLACK = (14, 11, 8)  # warm near-black, NOT cold navy
AGED_CREAM = (242, 235, 216)  # primary text on dark; off-white like printed ink
FLYER_RED = (216, 58, 37)  # oxidized vermillion — single shock accent, use ONCE per slide
INK_GRAY = (110, 104, 96)  # secondary/metadata text, dividers
MUTED_GOLD = (184, 145, 74)  # rare second accent, matches desk-lamp warmth in bg photo

# Translucent variants used for panels and overlays
PAPER_BLACK_WASH = (14, 11, 8, 210)  # semi-opaque wash for text panels
PAPER_BLACK_SHEER = (14, 11, 8, 140)  # lighter wash when we want bg photo to bleed through
AGED_CREAM_PANEL = (242, 235, 216, 245)  # solid-feeling cream panel with hint of transparency

# --- Spacing scale (8px base) ---
SP_XS = 8
SP_SM = 16
SP_MD = 24
SP_LG = 48
SP_XL = 96
SP_XXL = 144

# --- Canvas sizes ---
INSTAGRAM_SQUARE = (1080, 1080)
VIDEO_WIDESCREEN = (1920, 1080)

# --- Fonts ---
_FONTS_DIR = Path(__file__).resolve().parent / "fonts"
_SHIPPORI_BOLD = _FONTS_DIR / "ShipporiMinchoB1-Bold.ttf"

# Display font fallback chain. Shippori Mincho B1 Bold is the primary editorial
# display face (committed under commons/fonts/). Noto Serif CJK JP Bold is a
# system-installed fallback with a compatible mincho aesthetic. Final fallback
# is the Noto Sans CJK JP Bold that the body face uses.
_DISPLAY_FALLBACKS: tuple[tuple[Path, int | None], ...] = (
    (_SHIPPORI_BOLD, None),
    (Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"), 0),
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"), 0),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), None),
)

# Body font fallback chains. Noto Sans CJK JP is the workhorse — Latin + full
# Japanese (kanji + kana). DejaVu is a last-resort Latin-only fallback.
_BODY_BOLD_FALLBACKS: tuple[tuple[Path, int | None], ...] = (
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"), 0),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), None),
)
_BODY_REGULAR_FALLBACKS: tuple[tuple[Path, int | None], ...] = (
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 0),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), None),
)


def _load_font(
    fallbacks: tuple[tuple[Path, int | None], ...],
    size: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Walk a fallback chain and return the first usable font; never raise."""
    for path, index in fallbacks:
        try:
            if index is not None:
                return ImageFont.truetype(str(path), size, index=index)
            return ImageFont.truetype(str(path), size)
        except (OSError, ValueError):
            continue
    logger.warning("No usable TrueType font found in fallback chain; using PIL default")
    return ImageFont.load_default()


def display_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Editorial display face: Shippori Mincho B1 Bold → Noto Serif CJK → Noto Sans CJK."""
    return _load_font(_DISPLAY_FALLBACKS, size)


def body_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Body face: Noto Sans CJK JP (Regular or Bold) → DejaVu."""
    return _load_font(_BODY_BOLD_FALLBACKS if bold else _BODY_REGULAR_FALLBACKS, size)


# --- Layout helpers ---


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
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


@functools.lru_cache(maxsize=4)
def paper_grain(size: tuple[int, int], *, opacity: int = 20, seed: int = 42) -> Image.Image:
    """Procedural paper-grain noise overlay (cached by size).

    Returns an RGBA image of the given size with random monochrome grain at the
    specified alpha. Composite over any base image to add a subtle printed-paper
    texture. opacity=20 is ~8% — barely perceptible but breaks the digital flatness.
    Vectorized with numpy — a 1920×1080 overlay is ~100× faster than a Python loop.
    """
    width, height = size
    rng = np.random.default_rng(seed)
    values = rng.integers(0, 256, size=(height, width), dtype=np.uint8)
    alpha = np.full((height, width), opacity, dtype=np.uint8)
    rgba = np.stack([values, values, values, alpha], axis=-1)
    return Image.fromarray(rgba, mode="RGBA")


def apply_paper_grain(base: Image.Image, *, opacity: int = 20) -> Image.Image:
    """Composite a paper-grain overlay onto an RGB image. Returns an RGB image."""
    grain = paper_grain(base.size, opacity=opacity)
    rgba = base.convert("RGBA")
    rgba.alpha_composite(grain)
    return rgba.convert("RGB")


def scale_to_fill(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Scale-crop an image to fill the target size exactly."""
    target_w, target_h = target
    ratio = max(target_w / img.width, target_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = (new_w - target_w) // 2
    y = (new_h - target_h) // 2
    return resized.crop((x, y, x + target_w, y + target_h))


# --- Shared brand background loader ---
# The basement-flyer-wall photograph under `static/hakkoake_slide_background_202511.png`
# is the brand DNA. Both the Instagram and video pipelines used to re-resolve its
# path separately (one via __file__, one via settings.BASE_DIR). Consolidate here.
_BRAND_BG_FILENAME = "hakkoake_slide_background_202511.png"


@functools.lru_cache(maxsize=4)
def load_brand_background(target_size: tuple[int, int]) -> Image.Image | None:
    """Load the brand background photo scaled to fill target_size.

    Cached per target size so the file is only read once per canvas. Returns
    None if the file is missing, so callers can fall back gracefully.
    """
    bg_path = Path(settings.BASE_DIR).parent / "static" / _BRAND_BG_FILENAME
    try:
        bg = Image.open(bg_path).convert("RGB")
    except OSError as exc:
        logger.debug(f"Could not load brand background {bg_path}: {exc}")
        return None
    return scale_to_fill(bg, target_size)


def brand_wash_canvas(size: tuple[int, int]) -> Image.Image:
    """Build the shared base canvas: brand bg photo + dark wash.

    Used by every video slide. Falls back to a PAPER_BLACK canvas if the
    brand photo is unavailable.
    """
    base = load_brand_background(size)
    if base is None:
        base = Image.new("RGB", size, PAPER_BLACK)
    rgba = base.convert("RGBA")
    wash = Image.new("RGBA", size, PAPER_BLACK_WASH)
    rgba.alpha_composite(wash)
    return rgba.convert("RGB")


# --- Shared QR code builder ---
# Same call signature used by both pipelines so the QR card looks identical
# on Instagram and in the video.


def build_qr_code(url: str, size: int = 300) -> Image.Image:
    """Build a PAPER_BLACK-on-AGED_CREAM QR code resized to `size` square pixels."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color=PAPER_BLACK, back_color=AGED_CREAM)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def draw_torn_edge(
    draw: ImageDraw.ImageDraw,
    y: int,
    width: int,
    color: tuple[int, int, int],
    *,
    amplitude: int = 6,
    segments: int = 60,
    seed: int = 7,
) -> None:
    """Draw a horizontal torn-paper edge line across the canvas.

    Produces a subtle randomized polyline at the given y, suggesting a ripped
    edge where a photo panel meets a text panel. Draws the edge as a filled
    polygon from y-amplitude to the top of the frame, so the area above the
    tear stays the target color.
    """
    rng = random.Random(seed)  # noqa: S311 — decorative torn-edge jitter, not cryptographic
    step = width / segments
    points: list[tuple[int, int]] = [(0, 0)]
    for i in range(segments + 1):
        x = int(i * step)
        dy = rng.randint(-amplitude, amplitude)
        points.append((x, y + dy))
    points.append((width, 0))
    draw.polygon(points, fill=color)


# --- Brand mark (placeholder) ---
# Keep this minimal and corner-placed per the design decision to minimize
# branding. This is the ONLY place the wordmark string lives — if the
# brand spelling changes later, change it here.
BRAND_WORDMARK = "HAKKO-AKKEI"
BRAND_TAGLINE = "TOKYO LIVE HOUSES"


def draw_corner_wordmark(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    *,
    anchor: str = "lt",
    color: tuple[int, int, int] = INK_GRAY,
    size: int = 18,
) -> None:
    """Draw the minimal corner wordmark + tagline stacked.

    position is (x, y) of the anchor point. anchor uses PIL text anchor codes
    (lt=left-top, rt=right-top, lb=left-bottom, rb=right-bottom).
    """
    x, y = position
    font = body_font(size, bold=True)
    tagline_font = body_font(max(size - 6, 10), bold=False)

    if anchor in ("rb", "rt"):
        draw.text((x, y), BRAND_WORDMARK, font=font, fill=color, anchor=anchor)
        if anchor == "rt":
            draw.text((x, y + size + 4), BRAND_TAGLINE, font=tagline_font, fill=color, anchor=anchor)
        else:  # rb
            draw.text((x, y - size - 4), BRAND_TAGLINE, font=tagline_font, fill=color, anchor=anchor)
    else:
        draw.text((x, y), BRAND_WORDMARK, font=font, fill=color, anchor=anchor)
        if anchor == "lt":
            draw.text((x, y + size + 4), BRAND_TAGLINE, font=tagline_font, fill=color, anchor="lt")
        else:  # lb
            draw.text((x, y - size - 4), BRAND_TAGLINE, font=tagline_font, fill=color, anchor="lb")
