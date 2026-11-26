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
    "lana": {
        "coast": {"label": "Sommer an der Küste",
                  "words": ("classic sailboat", "wooden boat", "beach house", "sand dunes", "dock",
                            "lighthouse", "beach umbrella", "sunset beach", "boardwalk", "canoe"),
                  "roles": ("friends", "woman"), "archive": 3,
                  "lines": ("pov: summer, 1969. the radio's still on",
                            "for the summers you can't get back",
                            "pov: the last warm evening of the year")},
        "porch": {"label": "Veranda & Land",
                  "words": ("porch", "horse", "pickup truck", "picket fence", "stable", "ranch",
                            "swing", "hammock", "lemonade", "white dress"),
                  "roles": ("woman", "americana"), "archive": 3,
                  "lines": ("for the nights you can't explain",
                            "pov: the last warm evening of the year",
                            "pov: summer, 1969. the radio's still on")},
        "roadtrip": {"label": "Roadtrip",
                     "words": ("convertible", "road trip", "highway", "diner", "motel", "gas station",
                               "hitchhiking", "drive in", "sunglasses", "hair wind"),
                     "roles": ("friends", "americana"), "archive": 2,
                     "lines": ("pov: driving home with the windows down",
                               "for the summers you can't get back")},
        "family": {"label": "Familienfest",
                   "words": ("family picnic", "lawn", "garden party", "summer family", "picket fence",
                             "home movie", "polaroid", "vintage dress", "swing", "lemonade"),
                   "roles": ("friends", "friends2"), "archive": 4,
                   "lines": ("pov: summer, 1969. the radio's still on",
                             "for the summers you can't get back")},
    },
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
                 "lines": ("music for thinking in the dark", "for the quiet hours")},
        "quiet": {"label": "Stille Stunden",
                  "words": ("rain", "window light", "staircase", "bedroom", "typewriter", "rocking chair",
                            "radio", "jukebox", "mirror", "sunlight window"),
                  "roles": ("woman", "gear"), "archive": 0,
                  "lines": ("for the quiet hours", "pov: sunday morning, nowhere to be",
                            "music for thinking in the dark")},
    },
    "night": {
        "drive": {"label": "Nachtfahrt",
                  "words": ("night drive", "driving night", "rearview mirror", "light trails", "freeway",
                            "street lights", "highway", "bridge night", "car interior", "taxi"),
                  "roles": ("woman",), "archive": 0,
                  "lines": ("pov: 2 am, driving nowhere", "the drive home you don't want to end",
                            "pov: empty freeway, full moon")},
        "diner": {"label": "Diner & Neon",
                  "words": ("diner", "neon sign", "neon motel", "motel", "gas station", "jukebox",
                            "corner store", "vintage sign", "car wash", "laundromat"),
                  "roles": ("friends", "americana"), "archive": 0,
                  "lines": ("pov: the last diner still open", "for the city at 3 am")},
        "city": {"label": "Stadt bei Nacht",
                 "words": ("city lights", "skyline", "elevated train", "subway", "rooftop", "brownstone",
                           "apartment windows", "marquee", "blue hour", "rain"),
                 "roles": ("woman", "americana"), "archive": 0,
                 "lines": ("for the city at 3 am", "pov: 2 am, driving nowhere")},
    },
}
ALWAYS_ROLES = ("flag", "car")  # owner: US flag and a classic car in every Reel


def key_for(style: str | None, variant: str | None) -> str | None:
    if variant == "night":
        return "night"
    return style if style in THEMES else None


def choose(style: str | None, variant: str | None, previews: list[dict], run_key: str) -> str | None:
    """Least-used theme of the style in the preview history; ties broken per run."""
    key = key_for(style, variant)
    if key is None:
        return None
    names = list(THEMES[key])
    used = {n: 0 for n in names}
    for entry in previews:
        if entry.get("style") == key and entry.get("theme") in used and entry.get("kind", "daily") == "daily":
            used[entry["theme"]] += 1
    low = min(used.values())
    tied = [n for n in names if used[n] == low]
    return tied[int.from_bytes(hashlib.sha256(f"{run_key}|theme".encode()).digest()[:2], "big") % len(tied)]


def get(style: str | None, variant: str | None, theme: str | None) -> dict | None:
    key = key_for(style, variant)
    return THEMES.get(key or "", {}).get(theme or "")


def words(style, variant, theme, run_key: str, lanes: int) -> list[str]:
    """`lanes` search words: one classic car + the US flag, the rest from the theme."""
    info = get(style, variant, theme)
    if info is None:
        return []
    pool = list(info["words"])
    start = int.from_bytes(hashlib.sha256(f"{run_key}|themewords".encode()).digest()[:2], "big") % len(pool)
    pool = pool[start:] + pool[:start]
    cars = ("porsche", "land rover", "range rover", "classic car")
    car = cars[int.from_bytes(hashlib.sha256(f"{run_key}|themecar".encode()).digest()[:1], "big") % len(cars)]
    return [car, "american flag"] + pool[:max(0, lanes - 2)]


def roles(style, variant, theme) -> tuple[str, ...]:
    info = get(style, variant, theme)
    return ALWAYS_ROLES + tuple(info["roles"]) if info else ()


def archive_films(style, variant, theme, default: int) -> int:
    info = get(style, variant, theme)
    return min(default, int(info["archive"])) if info else default


def lines(style, variant, theme) -> tuple[str, ...]:
    info = get(style, variant, theme)
    return tuple(info["lines"]) if info else ()
