"""End-of-Reel title card: "carl e cool" + song title, rendered once as a transparent PNG.

Why a PNG (Pillow) instead of FFmpeg drawtext: any song title (quotes, colons, accents)
renders without filter-escaping risks, and the layout can shrink long titles to fit.
Placement: centred slightly above the middle, clear of Instagram/TikTok's bottom caption
area and right-hand buttons. Missing Pillow or fonts → the Reel simply has no card.
"""
from __future__ import annotations

import os
from pathlib import Path

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",          # GitHub ubuntu runners
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Helvetica.ttc",                       # macOS
    "/Library/Fonts/Arial.ttf",
)
TITLE_SECONDS = 2.2


def enabled() -> bool:
    return os.getenv("CARLECOOL_TITLE_CARD", "true").strip().lower() in ("true", "1", "yes", "on")


def _font(size: int):
    from PIL import ImageFont
    custom = os.getenv("CARLECOOL_TITLE_FONT", "").strip()
    for path in ((custom,) if custom else ()) + FONT_CANDIDATES:
        if path and Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _fit(draw, text: str, start_size: int, max_width: int):
    size = start_size
    while size > 18:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size = int(size * 0.92)
    return _font(size)


def make_title_card(artist: str, title: str, width: int, height: int, destination: Path) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return None
    artist = " ".join(str(artist).split()).lower()
    title = " ".join(str(title).split())
    if not title:
        return None
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    max_width = int(width * 0.82)
    title_font = _fit(draw, title, int(width * 0.072), max_width)
    # Widely tracked small artist line, like a film credit.
    spaced = " ".join(artist)
    artist_font = _fit(draw, spaced, int(width * 0.03), max_width)
    centre_y = int(height * 0.44)
    gap = int(height * 0.012)
    a_box = draw.textbbox((0, 0), spaced, font=artist_font)
    t_box = draw.textbbox((0, 0), title, font=title_font)
    a_h, t_h = a_box[3] - a_box[1], t_box[3] - t_box[1]
    top = centre_y - (a_h + gap + t_h) // 2
    a_xy = ((width - (a_box[2] - a_box[0])) // 2 - a_box[0], top - a_box[1])
    t_xy = ((width - (t_box[2] - t_box[0])) // 2 - t_box[0], top + a_h + gap - t_box[1])
    # Soft shadow for legibility on bright footage, without a hard box.
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.text(a_xy, spaced, font=artist_font, fill=(0, 0, 0, 150))
    sdraw.text(t_xy, title, font=title_font, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(2, width // 180)))
    canvas = Image.alpha_composite(canvas, shadow)
    draw = ImageDraw.Draw(canvas)
    draw.text(a_xy, spaced, font=artist_font, fill=(255, 255, 255, 215))
    draw.text(t_xy, title, font=title_font, fill=(255, 255, 255, 245))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, "PNG")
    return destination
