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
    # owner's video guide (27 Nov): melancholic decadence, Old-Hollywood glamour against
    # motel / gas-station Americana, hypnotic summer heat, analog home-movie texture,
    # California + desert + East Coast, water, classic cars, US flag; plus Old Money Hamptons.
    # People on screen: women only (owner, 27 Nov).
    "lana": {
        "california": {"label": "Kalifornien & Pool",
                       "words": ("palm trees", "swimming pool", "malibu", "venice beach", "convertible",
                                 "sunset boulevard", "pier", "surfer", "underwater", "ocean cliff"),
                       "roles": ("woman", "americana"), "archive": 2,
                       "lines": ("pov: summer, 1969. the radio's still on",
                                 "for the summers you can't get back",
                                 "pov: the pool after the party")},
        "desert": {"label": "Wüste & Motel",
                   "words": ("desert highway", "motel", "neon motel", "diner", "gas station", "empty pool",
                             "route 66", "vintage sign", "motorcycle", "desert sunset"),
                   "roles": ("woman", "americana"), "archive": 2,
                   "lines": ("pov: motel pool, 104 degrees",
                             "pov: driving home with the windows down",
                             "for the summers you can't get back")},
        "glamour": {"label": "Old Hollywood Glamour",
                    "words": ("chandelier", "mansion", "pearls", "champagne", "silk dress", "vintage dress",
                              "ballroom", "red lipstick", "vintage car", "marble staircase"),
                    "roles": ("woman", "friends"), "archive": 1,
                    "lines": ("for the nights you can't explain",
                              "pov: the last party at the mansion")},
        "hamptons": {"label": "Old Money Hamptons",
                     "words": ("beach house", "classic sailboat", "tennis", "country club", "white dress",
                               "lighthouse", "sand dunes", "estate lawn", "cable knit", "polo"),
                     "roles": ("woman", "friends"), "archive": 2,
                     "lines": ("pov: the last summer at the beach house",
                               "pov: the last warm evening of the year",
                               "for the summers you can't get back")},
        "homemovie": {"label": "Super-8-Erinnerung",
                      "words": ("home movie", "super 8", "polaroid", "lawn", "picket fence", "swing",
                                "lemonade", "vintage dress", "hair wind", "summer"),
                      "roles": ("friends", "woman"), "archive": 4,
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
                 "lines": ("pov: driving nowhere on a sunday", "for the quiet hours")},
        "quiet": {"label": "Stille Stunden",
                  "words": ("rain", "window light", "staircase", "bedroom", "typewriter", "rocking chair",
                            "radio", "jukebox", "mirror", "sunlight window"),
                  "roles": ("woman", "gear"), "archive": 0,
                  "lines": ("for the quiet hours", "pov: sunday morning, nowhere to be")},
    },
    # owner's night bible (27 Nov, "Concrete Crown & Midnight Horsepower"): old money ×
    # 90s NYC at night × stadium floodlights × air-cooled Porsche 993. Women only on screen.
    "night": {
        "drive": {"label": "993 Nachtfahrt",
                  "words": ("porsche", "night drive", "tunnel", "brooklyn bridge", "light trails", "east river",
                            "dashboard", "rearview mirror", "wet road", "skyline night"),
                  "roles": ("woman",), "archive": 0,
                  "lines": ("pov: 2 am, driving nowhere", "the drive home you don't want to end",
                            "pov: empty freeway, full moon")},
        "projects": {"label": "Brooklyn & Harlem bei Nacht",
                     "words": ("brooklyn", "harlem", "brick building", "fire escape", "steam street",
                               "street lamp", "basketball court", "chain fence", "alley night", "window lights"),
                     "roles": ("woman", "americana"), "archive": 0,
                     "lines": ("for the city at 3 am", "pov: brooklyn, 1996, the block is quiet")},
        "stadium": {"label": "Baseball unter Flutlicht",
                    "words": ("baseball field", "stadium lights", "floodlights", "stadium night", "baseball",
                              "bleachers", "dugout", "night fog", "baseball bat", "empty stadium"),
                    "roles": ("woman", "americana"), "archive": 0,
                    "lines": ("pov: the lights are still on at the ballpark", "for the city at 3 am")},
        "gilded": {"label": "Old Money bei Nacht",
                   "words": ("pool night", "mansion night", "chandelier", "camera flash", "pearls",
                             "velvet dress", "black dress", "limousine", "city lights", "rooftop"),
                   "roles": ("woman", "friends"), "archive": 0,
                   "lines": ("pov: the last party at the mansion", "for the nights you can't explain")},
    },
}
ALWAYS_ROLES = ("flag", "car")  # owner: US flag and a classic car in every Reel

# Music first (26 Nov): which kind of song suits a theme. Classes from analysis.py:
# tempo slow < 95 ≤ mid < 125 ≤ fast BPM; sound dark < 1800 ≤ warm < 2500 ≤ bright Hz
# (spectral centroid); percussion sparse < 0.15 ≤ groove; spacious = loud/quiet ≥ 2.8.
# "Energy" is left out: it reads 1.0 for every song of the EP (saturated, no signal).
MUSIC = {
    ("lana", "california"): {"tempo": "mid", "sound": "bright"},
    ("lana", "desert"): {"tempo": "fast", "drive": "groove"},
    ("lana", "glamour"): {"tempo": "slow", "sound": "dark", "space": "spacious"},
    ("lana", "hamptons"): {"tempo": "mid", "sound": "warm"},
    ("lana", "homemovie"): {"tempo": "slow", "sound": "warm", "drive": "sparse"},
    ("rubin", "studio"): {"tempo": "mid", "drive": "groove"},
    ("rubin", "coast"): {"tempo": "slow", "space": "spacious"},
    ("rubin", "road"): {"tempo": "mid", "sound": "warm"},
    ("rubin", "quiet"): {"tempo": "slow", "sound": "dark", "drive": "sparse"},
    ("night", "drive"): {"tempo": "fast", "drive": "groove"},
    ("night", "projects"): {"tempo": "mid", "sound": "dark", "drive": "groove"},
    ("night", "stadium"): {"tempo": "mid", "sound": "bright", "space": "spacious"},
    ("night", "gilded"): {"tempo": "slow", "sound": "warm", "space": "spacious"},
}
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
    if variant == "night":
        return "night"
    return style if style in THEMES else None


def choose(style: str | None, variant: str | None, previews: list[dict], run_key: str,
           features=None) -> str | None:
    """Theme that suits the song best (60 %) while every theme keeps its turn (40 %)."""
    key = key_for(style, variant)
    if key is None:
        return None
    names = list(THEMES[key])
    used = {n: 0 for n in names}
    for entry in previews:
        if entry.get("style") == key and entry.get("theme") in used and entry.get("kind", "daily") == "daily":
            used[entry["theme"]] += 1
    low, high = min(used.values()), max(used.values())
    classes = music_classes(features) if features is not None else {}

    def score(n):
        fair = 1.0 if high == low else (high - used[n]) / (high - low)
        fit = music_fit(key, n, classes)
        tie = int.from_bytes(hashlib.sha256(f"{run_key}|theme|{n}".encode()).digest()[:2], "big") / 65535 * 1e-3
        if fit is None:
            return fair + tie
        return MUSIC_SHARE * fit + (1 - MUSIC_SHARE) * fair + tie
    # never more than 2 Reels ahead of the least-used theme (no theme starves)
    eligible = [n for n in names if used[n] - low < 2] or names
    return max(eligible, key=score)


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
