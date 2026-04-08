# HAKKO-AKKEI Design System

Single source of truth for the visual language of every slide hakoake-backend
generates: Instagram carousel posts (1080×1080) and YouTube playlist videos
(1920×1080). All constants, fonts, and layout helpers live in
`malcom/commons/design.py`. The two consumer modules
(`malcom/commons/instagram_images.py` and `malcom/houses/functions.py`)
import from there. **Never hardcode a color, font, or padding constant in a
consumer module — add it to `commons/design.py` first.**

## Voice

Tokyo live-house basement flyer wall. Warm analog darkness. Aged-paper cream.
A single oxidized-vermillion shock color used sparingly. The brand background
photo at `static/hakkoake_slide_background_202511.png` is the eureka
reference — every slide should look like it belongs taped to that wall.

The vocabulary the design system enforces:

- **Editorial Japanese mincho serif** for display type, not sans
- **Asymmetric grid** with a strong left rail, not centered everything
- **Photos at full saturation** when we have them, not blurred-and-darkened
- **Paper grain** overlay on every composition to break digital flatness
- **Torn paper edges** where photo meets caption panel
- **Oversized vermillion numerals** for ranking — they are the punctuation

## Palette

Defined in `commons/design.py`:

| Constant | RGB | Use |
|----------|-----|-----|
| `PAPER_BLACK` | `(14, 11, 8)` | Backgrounds. Warm near-black, never cold navy. |
| `AGED_CREAM` | `(242, 235, 216)` | Primary text on dark; cream panels. |
| `FLYER_RED` | `(216, 58, 37)` | Single shock accent. **One use per slide.** Numerals + dates. |
| `INK_GRAY` | `(110, 104, 96)` | Secondary text, labels, the corner wordmark. |
| `MUTED_GOLD` | `(184, 145, 74)` | Rare second accent matching the bg desk-lamp warmth. |
| `PAPER_BLACK_WASH` | `(14, 11, 8, 210)` | Semi-opaque dark wash for text panels over photos. |
| `PAPER_BLACK_SHEER` | `(14, 11, 8, 140)` | Lighter wash when bg photo should bleed through. |
| `AGED_CREAM_PANEL` | `(242, 235, 216, 245)` | Solid-feeling cream panels (e.g. QR cards). |

## Typography

| Helper | Returns | Notes |
|--------|---------|-------|
| `display_font(size)` | Shippori Mincho B1 Bold → Noto Serif CJK Bold → Noto Sans CJK Bold → DejaVu | Editorial display serif. Use for performer names, period labels, big numerals. |
| `body_font(size, *, bold=False)` | Noto Sans CJK JP (Bold or Regular) → DejaVu | Use for metadata, labels, captions. |

The display face TTF is committed to the repo at
`malcom/commons/fonts/ShipporiMinchoB1-Bold.ttf` so the visual identity
does not depend on system-installed fonts. The fallback chain is forgiving
— if the TTF is ever missing, slides degrade gracefully to Noto Serif CJK
JP and still get a Japanese editorial mincho aesthetic.

The historical bug the system protects against: hardcoded DejaVu loaders
rendered every Japanese glyph as `.notdef` tofu boxes. **Never call
`ImageFont.truetype()` directly in a consumer module.** Always go through
`display_font()` or `body_font()`.

## Spacing scale

8px base unit. Use the constants, not raw integers, so layouts feel
consistent across the two pipelines.

| Constant | px |
|----------|----|
| `SP_XS` | 8 |
| `SP_SM` | 16 |
| `SP_MD` | 24 |
| `SP_LG` | 48 |
| `SP_XL` | 96 |
| `SP_XXL` | 144 |

## Canvas sizes

| Constant | Size | Use |
|----------|------|-----|
| `INSTAGRAM_SQUARE` | `(1080, 1080)` | All carousel slides. |
| `VIDEO_WIDESCREEN` | `(1920, 1080)` | Playlist video slides. |

## Layout helpers

All in `commons/design.py`:

- `wrap_text(draw, text, font, max_width)` — word-wrap a string into a list
  of lines that each fit within the given pixel width.
- `paper_grain(size, *, opacity=20, seed=42)` — cached procedural noise
  overlay (RGBA) for breaking digital flatness.
- `apply_paper_grain(base, *, opacity=20)` — composite paper grain over an
  RGB base image. Returns RGB.
- `scale_to_fill(img, target)` — scale-crop an image to fill the target
  size exactly (no letterboxing).
- `draw_torn_edge(draw, y, width, color, *, amplitude, segments, seed)` —
  draw a randomized torn-paper edge across the canvas; everything above
  `y` becomes the target color.
- `draw_corner_wordmark(draw, position, *, anchor, color, size)` — draw the
  minimal HAKKO-AKKEI corner mark + tagline. **This is the only place the
  wordmark string lives.** If the brand spelling changes, change it once
  in `BRAND_WORDMARK` / `BRAND_TAGLINE` in `commons/design.py`.

## Slide types

### Instagram carousel (1080×1080)

In `malcom/commons/instagram_images.py`:

| Function | Purpose |
|----------|---------|
| `generate_playlist_cover` | Numbered lineup cover. Brand bg + dark wash + paper grain. Big oversized vermillion numerals down the left rail with cream names. Corner wordmark bottom-left. |
| `generate_performer_card` | Top 62% performer photo at full saturation, torn edge, bottom 38% paper-black caption panel with display-serif name + romaji + venue/date. Oversized vermillion position numeral straddles the seam. |
| `generate_qr_slide` | PAPER_BLACK background. Left rail: editorial label + big numeral + name + venue/date. Right side: cream QR card. |
| `generate_combined_flyer_qr_slide` | Flyer-as-background at full saturation. Cream QR card bottom-right with name + venue + date. Position numeral top-left in vermillion. |

### Playlist video (1920×1080)

In `malcom/houses/functions.py`:

| Function | Purpose |
|----------|---------|
| `render_video_intro_slide` | Editorial header (HAKKO-AKKEI / period label) over the brand bg. Two-column numbered lineup, vermillion numerals + cream names, ★ for spotlights. |
| `render_video_performer_slide` | Left column: oversized position numeral, display-serif name, romaji, song title, venue/date. Right column: up to two cream QR cards (artist + venue), each labeled. |
| `render_video_closing_slide` | Big display-serif closing message. Centered cream QR card linking the YouTube channel. Music credit beneath, in INK_GRAY. |

The video generator (`_generate_playlist_video`) uses **hard cuts** between
slides — the previous glitch/RGB-shift transitions were retired with this
design pass. They fought the warm analog idiom.

## Adding a new slide

1. Decide which constant or helper you need. If `commons/design.py`
   doesn't have it, add it there *first*. Don't inline.
2. Pick the shared idioms: warm bg + paper grain, editorial display type
   in the left rail, vermillion only for one element.
3. Write the renderer in the appropriate consumer module
   (`commons/instagram_images.py` for square, `houses/functions.py` for
   widescreen). Import from `commons.design`.
4. Add a smoke test under `commons/tests/` or `houses/tests/` that asserts
   the renderer produces an image of the expected canvas size and does
   not crash on representative input.
5. Run `uv run poe test` and `uv run ruff check malcom/`.

## Anti-patterns to avoid

- **Centered everything.** Use the asymmetric grid with a strong left rail.
- **Cold blue-grey backgrounds.** Use `PAPER_BLACK`, never `(20, 20, 30)`.
- **Coral pink accents.** Use `FLYER_RED` (oxidized vermillion), never
  `(255, 100, 100)`.
- **DejaVu Sans Bold direct loads.** They render Japanese as tofu. Always
  go through `display_font` or `body_font`.
- **Glitch / scanline / RGB-shift effects.** Retired. They are at war with
  the warm analog look.
- **Multiple uses of FLYER_RED on a single slide.** It is the shock color.
  One element per slide owns it (usually the position numeral).
- **Heavy gaussian blur on performer photos.** Photos are the point. Show
  them at full saturation.
