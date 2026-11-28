"""One theme per Reel (owner, 26 Nov: "das Video ist nicht stimmig").

Reel #54 mixed six worlds (NYC architecture, aerial clouds, a 1940s farm film, a skate
park, a meadow, an AI clip) because 7 of ~50 search words per style were drawn at random,
and its text line promised a studio that never appeared. Now every Reel picks ONE theme
of its style; the search words, the signature roles, the archive share and the text line
all come from that theme. The car and the US flag stay in every Reel (owner's rule) —
as part of the scene, not as a separate world.

Themes rotate evenly per style (least used in the preview history first).
"""
from __future__ import annotations

import hashlib

# words: Coverr search words (≤ 2 words each, Coverr matches every word)
# roles: signature roles that fit the scene (flag + car are always added by main.py)
# archive: max. public-domain home movies (they are sunny 1940s–70s daylight footage)
# lines: on-screen text hook candidates (hooktext.py) — only lines the pictures can keep
THEMES: dict[str, dict[str, dict]] = {
    "rubin": {
        "studio": {"label": "Studio",
                   "words": ("record player", "turntable", "mixing console", "tape recorder", "reel tape",
                             "piano", "synthesizer", "white room", "wooden interior", "vinyl records"),
                   "roles": ("gear", "friends"), "archive": 0,
                   "lines": ("pov: the studio after everyone left", "pov: 2 am, one more take")},
        "coast": {"label": "Küste",
                  "words": ("beach house", "ocean", "sunlight window", "empty beach", "waves",
                            "white room", "porch", "golden hour", "silhouette", "rain"),
                  "roles": ("woman", "friends"), "archive": 1,
                  "lines": ("pov: sunday morning, nowhere to be", "for the quiet hours")},
        "road": {"label": "Straße",
                 "words": ("empty road", "pickup truck", "diner", "golden hour", "desert road",
                           "highway", "parking lot", "gas station", "rooftop", "street"),
                 "roles": ("friends",), "archive": 1,
                 "lines": ("pov: driving nowhere on a sunday", "for the quiet hours")},
        "quiet": {"label": "Stille Stunden",
                  "words": ("rain", "window light", "staircase", "bedroom", "typewriter", "rocking chair",
                            "radio", "jukebox", "mirror", "sunlight window"),
                  "roles": ("woman", "gear"), "archive": 0,
                  "lines": ("for the quiet hours", "pov: sunday morning, nowhere to be")},
    },
}
# Creative Directors (27 Nov): every director file brings its own themes (directors/*.json).
from . import directors as _directors  # noqa: E402
for _name, _themes in _directors.table("themes").items():
    THEMES[_name] = {t: {k: v for k, v in info.items() if k != "music"} for t, info in _themes.items()}
ALWAYS_ROLES = ("flag", "car")  # owner: US flag and a classic car in every Reel

# Music first (26 Nov): which kind of song suits a theme. Classes from analysis.py:
# tempo slow < 95 ≤ mid < 125 ≤ fast BPM; sound dark < 1800 ≤ warm < 2500 ≤ bright Hz
# (spectral centroid); percussion sparse < 0.15 ≤ groove; spacious = loud/quiet ≥ 2.8.
# "Energy" is left out: it reads 1.0 for every song of the EP (saturated, no signal).
MUSIC = {
    ("rubin", "studio"): {"tempo": "mid", "drive": "groove"},
    ("rubin", "coast"): {"tempo": "slow", "space": "spacious"},
    ("rubin", "road"): {"tempo": "mid", "sound": "warm"},
    ("rubin", "quiet"): {"tempo": "slow", "sound": "dark", "drive": "sparse"},
}
for _name, _themes in _directors.table("themes").items():
    MUSIC.update({(_name, t): dict(info.get("music") or {}) for t, info in _themes.items()})
ORDER = {"tempo": ("slow", "mid", "fast"), "sound": ("dark", "warm", "bright"),
         "drive": ("sparse", "groove"), "space": ("tight", "spacious")}
WEIGHT = {"tempo": 0.35, "sound": 0.3, "drive": 0.2, "space": 0.15}  # energy, cover: no usable signal
MUSIC_SHARE = 0.6  # theme choice = 60 % musical fit + 40 % even rotation


def music_classes(features) -> dict[str, str]:
    """Classes of the song; a missing measurement (0) gives no class."""
    out = {}
    bpm = float(getattr(features, "bpm", 0) or 0)
    if bpm:
        out["tempo"] = "slow" if bpm < 95 else "mid" if bpm < 125 else "fast"
    hz = float(getattr(features, "timbre_hz", 0) or 0)
    if hz:
        out["sound"] = "dark" if hz < 1800 else "warm" if hz < 2500 else "bright"
    perc = float(getattr(features, "percussive", 0) or 0)
    if perc:
        out["drive"] = "sparse" if perc < 0.15 else "groove"
    dyn = float(getattr(features, "dynamics", 0) or 0)
    if dyn:
        out["space"] = "spacious" if dyn >= 2.8 else "tight"
    return out


def music_fit(key: str, theme: str, classes: dict[str, str]) -> float | None:
    """0..1: how well the song suits the theme (neighbouring class = half); None = unknown."""
    wants = MUSIC.get((key, theme)) or {}
    num = den = 0.0
    for dim, want in wants.items():
        have = classes.get(dim)
        if have is None:
            continue
        steps = abs(ORDER[dim].index(have) - ORDER[dim].index(want))
        num += WEIGHT[dim] * (1.0 if steps == 0 else 0.5 if steps == 1 and len(ORDER[dim]) > 2 else 0.0)
        den += WEIGHT[dim]
    return num / den if den else None


def key_for(style: str | None, variant: str | None) -> str | None:
    key = _directors.key(style, variant)
    return key if key in THEMES else None


def choose(style: str | None, variant: str | None, previews: list[dict], run_key: str,
           features=None) -> str | None:
    """Theme that suits the song best (60 %) while every theme keeps its turn (40 %)."""
    key = key_for(style, variant)
    if key is None:
        return None
    import os
    forced = os.getenv("CARLECOOL_THEME", "").strip().lower()
    if forced and forced in THEMES[key]:
        return forced  # manual test run (workflow input `theme`)
    names = list(THEMES[key])
    used = {n: 0 for n in names}
    for entry in previews:
        if entry.get("style") == key and entry.get("theme") in used and entry.get("kind", "daily") == "daily":
            used[entry["theme"]] += 1
    # Motif weights of the director (unified bible, 27 Nov: e.g. analog music 25 %, Royals
    # 10 %): a theme's use is counted relative to its weight. Equal weights = plain rotation.
    weight = {n: float(THEMES[key][n].get("weight") or 1.0) for n in names}
    top = max(weight.values())
    ahead = {n: used[n] * top / weight[n] for n in names}
    low, high = min(ahead.values()), max(ahead.values())
    classes = music_classes(features) if features is not None else {}

    def score(n):
        fair = 1.0 if high == low else (high - ahead[n]) / (high - low)
        fit = music_fit(key, n, classes)
        tie = int.from_bytes(hashlib.sha256(f"{run_key}|theme|{n}".encode()).digest()[:2], "big") / 65535 * 1e-3
        if fit is None:
            return fair + tie
        return MUSIC_SHARE * fit + (1 - MUSIC_SHARE) * fair + tie
    # never more than 2 Reels ahead of the least-used theme (no theme starves)
    eligible = [n for n in names if ahead[n] - low < 2] or names
    return max(eligible, key=score)


def get(style: str | None, variant: str | None, theme: str | None) -> dict | None:
    key = key_for(style, variant)
    return THEMES.get(key or "", {}).get(theme or "")


def words(style, variant, theme, run_key: str, lanes: int, theme_only: bool = False) -> list[str]:
    """`lanes` search words: one classic car + the US flag, the rest from the theme.
    `theme_only` (cinematic, 28 Nov): every lane searches the theme — car and flag come
    through their own, stricter signature roles (search lanes brought a river for
    "land rover" and a Ford for "american flag" in Reel #92)."""
    info = get(style, variant, theme)
    if info is None:
        return []
    pool = list(info["words"])
    start = int.from_bytes(hashlib.sha256(f"{run_key}|themewords".encode()).digest()[:2], "big") % len(pool)
    pool = pool[start:] + pool[:start]
    cars = ("porsche", "land rover", "range rover", "classic car")
    car = cars[int.from_bytes(hashlib.sha256(f"{run_key}|themecar".encode()).digest()[:1], "big") % len(cars)]
    if theme_only:
        return pool[:lanes]
    return [car, "american flag"] + pool[:max(0, lanes - 2)]


def roles(style, variant, theme) -> tuple[str, ...]:
    """Signature roles: the director's always-roles (flag, car, analog gear) + the theme's."""
    info = get(style, variant, theme)
    if not info:
        return ()
    d = _directors.get(key_for(style, variant))
    # a theme may set its own always-roles (the #73 reference theme had no analog gear)
    always = tuple(info.get("always_roles") or (d or {}).get("always_roles") or ALWAYS_ROLES)
    return always + tuple(r for r in info["roles"] if r not in always)


def archive_films(style, variant, theme, default: int) -> int:
    info = get(style, variant, theme)
    return min(default, int(info["archive"])) if info else default


def lines(style, variant, theme) -> tuple[str, ...]:
    info = get(style, variant, theme)
    return tuple(info["lines"]) if info else ()
