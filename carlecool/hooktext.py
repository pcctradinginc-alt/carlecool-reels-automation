"""On-screen text hook in the first seconds — as an A/B test (owner, 25 Nov).

The first 7 TikTok Reels were watched ~2.4 s on average, whatever their length. A short,
quiet line at the top ("pov: 2 am, driving nowhere") is a known lever for instrumental
music: it gives the viewer a scene to project the song into. It is tested, not assumed:
half of the Reels get a line, half don't, and performance.py compares both once enough
posts exist (then the better variant is used more often, the other keeps being tested).

Lowercase, understated, English (international audience), no hashtags, no claims about
how the music was made. Rendered with Pillow as a transparent PNG and laid over the first
~2.6 s by render.py (works with any FFmpeg build, no drawtext needed).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

SAFE_TOP, SAFE_BOTTOM = 0.12, 0.22
HOOK_SECONDS = 2.6  # visible from the start, gone before the first musical phrase ends
LINES = {
    "rubin": ("pov: 2 am, one more take",
              "for the quiet hours",
              "pov: the studio after everyone left",
              "music for thinking in the dark",
              "pov: sunday morning, nowhere to be"),
}
# Creative Directors (27 Nov): fallback lines per director (themes bring their own).
from . import directors as _directors  # noqa: E402
for _n, _d in _directors.load_all().items():
    if _d.get("hook_lines"):
        LINES[_n] = tuple(_d["hook_lines"])
_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
# Owner, 28 Nov: the font of the Twin Peaks opening credits — ITC Avant Garde Gothic
# Condensed in green. TeX Gyre Adventor is its free clone (GUST licence, assets/fonts);
# the condensed cut is made by narrowing the rendered line (CONDENSE).
TWIN_PEAKS_GREEN = (118, 196, 96, 245)
GLOW = (14, 46, 20, 200)
CONDENSE = 0.82
FONTS = (
    str(_ASSETS / "texgyreadventor-regular.otf"),
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",   # GitHub ubuntu runners
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",             # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def enabled() -> bool:
    return os.getenv("CARLECOOL_TEXT_HOOK", "test").strip().lower() not in ("off", "false", "0", "no")


def _share(key: str) -> float:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") / 65535


def choose(world: str | None, variant: str | None, run_key: str, prefer: str | None = None,
           lines: tuple[str, ...] | None = None) -> str:
    """The line for this Reel, or "" (no text). 50/50 while testing; once performance.py
    has a winner ("text" / "none"), 70 % of the Reels follow it and 30 % keep testing.
    CARLECOOL_TEXT_HOOK=always / off forces it."""
    mode = os.getenv("CARLECOOL_TEXT_HOOK", "test").strip().lower()
    if mode in ("off", "false", "0", "no"):
        return ""
    key = _directors.key(world, variant)
    key = key if key in LINES else "lana"
    pool = tuple(lines) if lines else LINES[key]  # theme lines: only what the pictures can keep
    line = pool[int.from_bytes(hashlib.sha256(f"{run_key}|hookline".encode()).digest()[:2], "big") % len(pool)]
    if mode == "always":
        return line
    want = 0.5
    if prefer == "text":
        want = 0.7
    elif prefer == "none":
        want = 0.3
    return line if _share(f"{run_key}|hooktext") < want else ""


def _font(size: int):
    from PIL import ImageFont
    for path in FONTS:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return None


def make_png(text: str, width: int, height: int, path: Path) -> Path | None:
    """Transparent full-frame PNG with the line in the upper third; None without a font."""
    if not text:
        return None
    from PIL import Image, ImageDraw, ImageFilter
    font = _font(max(18, int(width * 0.055)))
    if font is None:
        print("Text hook skipped: no font available")
        return None
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    max_w = int(width * 0.8)
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    line_h = int(font.size * 1.3)
    # Phase 4: platform safe zones — TikTok / Instagram UI covers ~12 % at the top and
    # ~22 % at the bottom; the text block always starts at 20 % and must end above 78 %.
    y0 = int(height * 0.2)
    if y0 + len(lines) * line_h > height * (1 - SAFE_BOTTOM):
        y0 = max(int(height * SAFE_TOP), int(height * (1 - SAFE_BOTTOM)) - len(lines) * line_h)
    twin_peaks = Path(getattr(font, "path", "")).name.startswith("texgyreadventor")
    fill = TWIN_PEAKS_GREEN if twin_peaks else (255, 250, 240, 235)
    halo = GLOW if twin_peaks else (0, 0, 0, 170)
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    for i, ln in enumerate(lines):
        x = (width - draw.textlength(ln, font=font) * (CONDENSE if twin_peaks else 1.0)) / 2
        y = y0 + i * line_h
        if twin_peaks:
            # render the line wide, then narrow it horizontally (Avant Garde *Condensed* look)
            w_line = int(draw.textlength(ln, font=font)) + 8
            line = Image.new("RGBA", (w_line, line_h), (0, 0, 0, 0))
            ImageDraw.Draw(line).text((0, 0), ln, font=font, fill=fill)
            line = line.resize((max(1, int(w_line * CONDENSE)), line_h), Image.LANCZOS)
            glow = Image.new("RGBA", line.size, halo)
            glow.putalpha(line.getchannel("A").point(lambda a: int(a * halo[3] / 255)))
            shadow.alpha_composite(glow, (int(x), int(y)))
            layer.alpha_composite(line, (int(x), int(y)))
        else:
            sdraw.text((x + 2, y + 2), ln, font=font, fill=halo)
            draw.text((x, y), ln, font=font, fill=fill)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(2, width // (180 if twin_peaks else 270))))
    out = Image.alpha_composite(shadow, layer)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    return path
