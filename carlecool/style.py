"""Two style worlds, always one of them, chosen by cover and music.

1. "lana"  — Lana × European Gen Z youth × Americana: friends in European streets inside a
   nostalgic Americana dream (faded flags, motels, diners, neon, roadtrips). Dreamy,
   wistful editing: long shots in quiet passages, soft dissolves, subtle slow motion,
   faded pastel palette, 35 mm grain and warm light leaks.
2. "rubin" — Rick Rubin × European Gen Z youth × Americana: raw, honest, documentary
   youth culture with sparse, symbolic Americana. Fewer, longer shots, hard and
   restrained cuts, stillness; peaks get closer (punch-in), not busier. Restrained
   grade, fine grain, slight exposure variation.

A dark cover adds the "night" variant to either world (neon, night streets, amber light).

Lesson from the reverted Creative v5 (generic subject queries made videos worse): a style
still only NUDGES the proven v4 pipeline: lane weights are blended 50/50 with the owner's
profile; the Gen Z friends / Americana / skater / woman shots are ADDED as signature
shots; the v4 clips stay in the edit.

Decision: a clearly recognised cover decides the world; otherwise the music decides
(slow or sparse tracks → Rubin, everything else → Lana). Overrides: profile "style"
(/revise stil lana|rubin|night|auto) or repo variable CARLECOOL_STYLE ("night" forces the
night variant, world from cover/music); CARLECOOL_STYLE=off disables the feature.
"""
from __future__ import annotations

import os
from pathlib import Path

STYLES = ("lana", "rubin")
LABELS = {"lana": "Lana × Gen Z × Americana", "rubin": "Rick Rubin × Gen Z × Americana"}

PROMPTS = {
    "lana": (
        "a rider on a horse with an american flag",
        "a cowboy on horseback in an open landscape",
        "a vintage american car on a desert highway",
        "a woman in a summer dress in a golden field",
        "palm trees and a motel sign at sunset",
        "an american flag waving in the wind",
        "young friends at a neon-lit diner at night",
    ),
    "rubin": (
        "a planet floating in outer space",
        "the earth seen from space",
        "a minimalist abstract sphere on a plain background",
        "a calm ocean horizon with an empty sky",
        "a single stone in a quiet zen garden",
        "a quiet black and white documentary photo of young people",
    ),
}
# Coverr matches every word: short motif queries that echo the cover's subject.
MOTIF_QUERIES = {
    "a rider on a horse with an american flag": ("horse riding", "american flag", "horse"),
    "a cowboy on horseback in an open landscape": ("cowboy", "horse riding", "horse"),
    "a vintage american car on a desert highway": ("vintage car", "desert road", "road trip"),
    "a woman in a summer dress in a golden field": ("golden field", "wheat field", "summer field"),
    "palm trees and a motel sign at sunset": ("palm trees", "motel", "sunset"),
    "an american flag waving in the wind": ("american flag", "flag", "sunset"),
    "young friends at a neon-lit diner at night": ("diner", "neon sign", "friends night"),
    "a planet floating in outer space": ("planet", "space", "stars"),
    "the earth seen from space": ("earth space", "planet", "space"),
    "a minimalist abstract sphere on a plain background": ("sphere", "minimal", "moon"),
    "a calm ocean horizon with an empty sky": ("ocean horizon", "calm ocean", "ocean"),
    "a single stone in a quiet zen garden": ("zen", "stone", "nature"),
    "a quiet black and white documentary photo of young people": ("friends walking", "street", "city"),
}
STYLE_WEIGHTS = {
    "lana": {"nature": 20, "studio": 5, "americana": 50, "skate": 10, "y2k": 5, "night": 10},
    "rubin": {"nature": 40, "studio": 25, "americana": 20, "skate": 10, "y2k": 0, "night": 5},
}
NIGHT_SHIFT = {"night": 20, "nature": -10, "studio": -5, "americana": -5}

# Extra grade AFTER the cover LUT; deliberately mild.
GRADES = {
    # Faded red / dusty blue / cream: lifted, slightly blue shadows, warm cream highlights.
    "lana": ["colortemperature=temperature=5600:mix=0.4",
             "curves=r='0/0.06 0.5/0.53 1/0.97':g='0/0.05 0.5/0.51 1/0.95':b='0/0.09 0.5/0.49 1/0.91'",
             "eq=saturation=0.92", "vignette=angle=PI/5"],
    # Warm ivory, faded denim, concrete grey: restrained, honest, lightly lifted.
    "rubin": ["colortemperature=temperature=6100:mix=0.25", "eq=saturation=0.86:contrast=0.97",
              "curves=all='0/0.04 0.5/0.5 1/0.96'", "vignette=angle=PI/6"],
}
NIGHT_GRADES = {
    # Dusky blue shadows, amber night light, neon kept but not glossy.
    "lana": ["colorbalance=bs=0.06:rh=0.05:gh=0.02:bh=-0.04",
             "curves=all='0/0.05 0.5/0.49 1/0.95'", "eq=saturation=0.95:gamma=0.97",
             "vignette=angle=PI/4.5"],
    "rubin": ["colorbalance=bs=0.04:rh=0.04:bh=-0.03", "eq=saturation=0.84:gamma=0.96",
              "curves=all='0/0.04 1/0.95'", "vignette=angle=PI/5"],
}
# Editing language, applied by render.py per shot (with the music's beat energy).
LOOKS = {
    "lana": {"dissolve": 0.42, "dissolve_below": 0.5,   # soft cuts in quiet passages
             "slowmo": 1.25, "slowmo_below": 0.34,          # subtle slow motion when it breathes
             "light_leaks": True, "grain_boost": 2, "punch_in_above": None, "exposure_jitter": 0.0},
    "rubin": {"dissolve": 0.0, "dissolve_below": 0.0,      # hard, restrained cuts
              "slowmo": 1.0, "slowmo_below": 0.0,
              "light_leaks": False, "grain_boost": 1,
              "punch_in_above": 0.75,                        # peaks: closer, not busier
              "exposure_jitter": 0.018},
}
DARK_BRIGHTNESS = 0.24
MIN_SCORE = 0.20
MIN_MARGIN = 0.008
SLOW_BPM = 100.0
SPARSE_ENERGY = 0.42


def mode() -> str:
    return os.getenv("CARLECOOL_STYLE", "auto").strip().lower() or "auto"


DARK_TIMBRE_HZ = 1800.0   # warm, dark sound (e.g. "chronocyte horizon" ≈ 1500 Hz) → Rubin
AMBIENT_PERCUSSIVE = 0.08  # almost no drums (pads/ambient) → Rubin
SPACIOUS_DYNAMICS = 2.8    # lots of space between loud and quiet → Rubin


def music_style(features) -> tuple[str, str]:
    """World from the music alone.

    Rubin: slow (≤ 100 BPM), calm, sparse, a dark/warm timbre, almost no percussion or lots
    of dynamic space. Lana: brighter, flowing tracks. Calibrated on the owner's catalogue
    (owner verdict: "chronocyte horizon" = Rubin; "luère froid" = Lana; "NAD+" = Rubin).
    """
    bpm = float(getattr(features, "bpm", 0) or 0)
    energy = [float(e) for e in (getattr(features, "beat_energy", ()) or ())]
    mean = sum(energy) / len(energy) if energy else 1.0
    timbre = float(getattr(features, "timbre_hz", 0) or 0)
    perc = float(getattr(features, "percussive", 0) or 0)
    dyn = float(getattr(features, "dynamics", 0) or 0)
    if getattr(features, "mood", "") == "calm":
        return "rubin", "music: calm"
    if 0 < bpm <= SLOW_BPM:
        return "rubin", f"music: slow ({bpm:.0f} BPM)"
    if mean < SPARSE_ENERGY:
        return "rubin", f"music: sparse (energy {mean:.2f})"
    if 0 < timbre < DARK_TIMBRE_HZ:
        return "rubin", f"music: dark, warm sound ({timbre:.0f} Hz)"
    if 0 < perc < AMBIENT_PERCUSSIVE:
        return "rubin", f"music: ambient, few drums ({perc:.2f})"
    if dyn >= SPACIOUS_DYNAMICS:
        return "rubin", f"music: lots of space (dynamics {dyn:.1f})"
    return "lana", f"music: {bpm:.0f} BPM, bright and flowing" + (f" ({timbre:.0f} Hz)" if timbre else "")


def decide(scores: dict[str, tuple[float, str]], brightness: float | None, features=None) -> dict:
    """Pure decision from per-style (best similarity, best prompt), cover brightness, music."""
    variant = "night" if brightness is not None and brightness < DARK_BRIGHTNESS else None
    night_note = f" · night (dark cover {brightness:.2f})" if variant else ""
    ranked = sorted(((s, v) for s, v in scores.items() if s in STYLES), key=lambda item: -item[1][0])
    if ranked:
        best, (score, prompt) = ranked[0]
        second = ranked[1][1][0] if len(ranked) > 1 else 0.0
        if score >= MIN_SCORE and score - second >= MIN_MARGIN:
            return {"style": best, "variant": variant, "basis": f"cover: {prompt}{night_note}",
                    "prompt": prompt, "score": round(score, 4), "margin": round(score - second, 4)}
    chosen, reason = music_style(features)
    out = {"style": chosen, "variant": variant, "basis": f"{reason}{night_note}", "prompt": ""}
    if ranked:
        out.update(score=round(ranked[0][1][0], 4))
    return out


def analyze(cover: Path | None, *, override: str = "auto", features=None) -> dict:
    """Choose world + variant for this Reel; never raises."""
    chosen = mode() if override in ("", "auto") else override
    if chosen == "off":
        return {"style": None, "variant": None, "basis": "disabled", "prompt": ""}
    if chosen in STYLES:
        variant = None
        brightness = _brightness(cover)
        if brightness is not None and brightness < DARK_BRIGHTNESS:
            variant = "night"
        return {"style": chosen, "variant": variant, "basis": "manual", "prompt": ""}
    force_night = chosen == "night"
    brightness = _brightness(cover)
    scores = _cover_scores(cover) if cover is not None else {}
    decision = decide(scores, brightness, features)
    if force_night and decision.get("variant") != "night":
        decision["variant"] = "night"
        decision["basis"] += " · night (manual)"
    return decision


def _brightness(cover: Path | None) -> float | None:
    if cover is None:
        return None
    try:
        from .curation import palette_traits
        return palette_traits(cover)["brightness"]
    except Exception as exc:
        print("Cover palette unavailable for style:", type(exc).__name__)
        return None


def _cover_scores(cover: Path) -> dict[str, tuple[float, str]]:
    scores: dict[str, tuple[float, str]] = {}
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is None:
        return scores
    try:
        import torch
        from .semantic import _frame
        model, preprocess, tokenizer = clip
        items = [(style, p) for style in STYLES for p in PROMPTS[style]]
        with torch.no_grad():
            img = torch.nn.functional.normalize(
                model.encode_image(preprocess(_frame(cover, 0)).unsqueeze(0)), dim=-1)
            txt = torch.nn.functional.normalize(
                model.encode_text(tokenizer([f"a photo of {p}" for _, p in items])), dim=-1)
            sims = (img @ txt.T)[0].tolist()
        for (style, prompt), sim in zip(items, sims):
            if style not in scores or sim > scores[style][0]:
                scores[style] = (float(sim), prompt)
    except Exception as exc:
        print("Cover style analysis failed:", type(exc).__name__)
        return {}
    return scores


def blended_weights(profile_weights: dict, style: str | None, variant: str | None = None) -> dict:
    if style not in STYLE_WEIGHTS:
        return dict(profile_weights)
    target = dict(STYLE_WEIGHTS[style])
    if variant == "night":
        target = {k: max(0, v + NIGHT_SHIFT.get(k, 0)) for k, v in target.items()}
    return {k: int(round(0.5 * int(profile_weights.get(k, 0)) + 0.5 * target[k])) for k in target}


def pace_for(profile_pace: str, style: str | None) -> str:
    return "slow" if style == "rubin" and profile_pace == "medium" else profile_pace


def grade_filters(style: str | None, variant: str | None = None) -> list[str]:
    table = NIGHT_GRADES if variant == "night" else GRADES
    return list(table.get(style or "", []))


def look(style: str | None) -> dict | None:
    return dict(LOOKS[style]) if style in LOOKS else None


def label(decision: dict) -> str:
    base = LABELS.get(decision.get("style") or "", "v4 default")
    return base + (" · Night" if decision.get("variant") == "night" and decision.get("style") else "")


def motif_queries(decision: dict) -> tuple[str, ...]:
    """Motif echo only when the cover was clearly recognised (no guessing on unclear covers)."""
    if not decision.get("style") or decision.get("basis") == "manual":
        return ()
    return MOTIF_QUERIES.get(decision.get("prompt") or "", ())


# Fixed Coverr search words per world (owner: motel, diner, roadtrip, friends at night,
# flag, neon, classic cars — a classic Porsche 911 / 993 or a classic Land Rover Defender
# rather than generic cars).
# Short words only: Coverr matches every word of a query.
SEARCH_QUERIES = {
    "lana": ("motel", "diner", "road trip", "friends night", "american flag", "neon sign",
             "porsche", "land rover", "classic car", "convertible", "palm trees", "gas station",
             "summer friends", "desert road", "sunset drive", "jukebox", "retro"),
    "rubin": ("friends walking", "basketball court", "parking lot", "empty road", "american flag",
              "land rover", "porsche", "classic car", "pickup truck", "diner", "rooftop", "skatepark",
              "golden hour", "friends talking", "street"),
}
NIGHT_QUERIES = {
    "lana": ("neon sign", "motel", "diner", "night drive", "friends night", "gas station",
             "porsche", "city lights", "american flag", "neon"),
    "rubin": ("friends night", "parking lot", "gas station", "night drive", "street night",
              "american flag", "porsche", "basketball court"),
}
SEARCH_LANES = 5
# Fallback when a style word finds nothing on Coverr (style words never broaden into
# generic lane words such as "road" or "nature").
SEARCH_FALLBACK = {"porsche": ("classic car", "vintage car"), "classic car": ("vintage car",),
                   "land rover": ("defender", "off road"),
                   "jukebox": ("retro",), "convertible": ("classic car",), "motel": ("motel sign",),
                   "neon sign": ("neon",), "friends night": ("friends",), "summer friends": ("friends",),
                   "pickup truck": ("truck",), "american flag": ("flag",), "road trip": ("road",),
                   "gas station": ("gas station night",), "diner": ("retro diner",)}


def search_ladders(words: list[str]) -> dict[str, tuple[str, ...]]:
    return {w: SEARCH_FALLBACK.get(w, ()) for w in words}


def search_queries(decision: dict, run_key: str = "", lanes: int = SEARCH_LANES) -> list[str]:
    """`lanes` style words for this run, rotated so consecutive Reels search differently;
    always one car (Porsche / classic car) and the flag in the mix."""
    import hashlib
    world = decision.get("style")
    if world not in SEARCH_QUERIES:
        return []
    pool = list((NIGHT_QUERIES if decision.get("variant") == "night" else SEARCH_QUERIES)[world])
    start = int.from_bytes(hashlib.sha256(f"{run_key}|search".encode()).digest()[:2], "big") % len(pool)
    pool = pool[start:] + pool[:start]
    cars = ("porsche", "land rover", "classic car")
    must = [q for q in pool if q in cars][:1] + ["american flag"]
    rest = [q for q in pool if q not in must and q not in cars]
    return (must + rest)[:lanes]


# Text for the optional AI shot (no artist names, no celebrity likeness, no logos).
AI_DIRECTION = {
    "lana": ("Small group of European friends aged 18 to 25 in 2026, baggy denim and thrifted "
             "jackets, laughing on a curb outside a neon motel diner, faded weathered American "
             "flag in the background, golden hour, dreamy nostalgic Americana, pastel faded red "
             "and dusty blue, 35mm grain, light leak, soft contrast, candid handheld"),
    "rubin": ("Two young European friends aged 18 to 25 sitting in silence on a parking lot at "
              "dusk, old pickup truck and sun-faded American flag on a fence far behind, "
              "documentary realism, static frame with negative space, warm ivory and concrete "
              "grey, fine 35mm grain, natural skin texture, restrained"),
}
