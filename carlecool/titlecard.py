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


COVER_CARD_SECONDS = 2.6


def make_cover_card(cover: Path, artist: str, title: str, width: int, height: int,
                    destination: Path) -> Path | None:
    """End card with the song's own artwork: the recognisable "this is carl e cool" frame.

    Layout (transparent PNG over the last ~2.6 s):
    * a dark scrim over the whole video so the artwork stands out on any footage,
    * the square cover (~64 % of the width) slightly above centre, with soft shadow,
    * tracked artist line and song title underneath.
    The same frame is used as the Instagram/TikTok cover image (thumbnail).
    Returns None (→ text-only card) if Pillow or the artwork are unavailable.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(cover) as raw:
            art = ImageOps.exif_transpose(raw).convert("RGB")
    except (OSError, ValueError):
        return None
    artist = " ".join(str(artist).split()).lower()
    title = " ".join(str(title).split())
    side = int(width * 0.64)
    art = ImageOps.fit(art, (side, side), method=Image.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (8, 8, 10, 120))
    left = (width - side) // 2
    top = int(height * 0.40) - side // 2
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([left + 6, top + 14, left + side + 6, top + side + 14],
                                     fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(4, width // 60)))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(art, (left, top))
    draw = ImageDraw.Draw(canvas)
    max_width = int(width * 0.82)
    spaced = " ".join(artist)
    artist_font = _fit(draw, spaced, int(width * 0.03), max_width)
    title_font = _fit(draw, title, int(width * 0.06), max_width)
    y = top + side + int(height * 0.035)
    for text, font, fill in ((spaced, artist_font, (255, 255, 255, 210)),
                             (title, title_font, (255, 255, 255, 245))):
        box = draw.textbbox((0, 0), text, font=font)
        x = (width - (box[2] - box[0])) // 2 - box[0]
        draw.text((x, y - box[1]), text, font=font, fill=fill)
        y += (box[3] - box[1]) + int(height * 0.014)
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, "PNG")
    return destination
