"""Cover-led style packages: Lana (Americana), Rubin (minimal/cosmic), Night.

Lesson from the reverted Creative v5: replacing the v4 search lanes with generic
subject queries made the videos clearly worse. A style here therefore only NUDGES
the proven v4 pipeline:
  * lane weights are blended 50/50 with the owner's profile (never replaced),
  * a light extra colour grade on top of the cover LUT,
  * Rubin calms the cutting only if the owner left pace at "medium",
  * one "motif" search echoes the cover's subject (horse rider → horse riding …).
Unclear covers return no style → v4 behaviour unchanged.
Overrides: profile "style" (via /revise stil lana|rubin|night|auto) or repo variable
CARLECOOL_STYLE; CARLECOOL_STYLE=off disables the feature.
"""
from __future__ import annotations

import os
from pathlib import Path

STYLES = ("lana", "rubin", "night")
LABELS = {"lana": "Lana / Americana", "rubin": "Rick Rubin / Minimal", "night": "Night"}

PROMPTS = {
    "lana": (
        "a rider on a horse with an american flag",
        "a cowboy on horseback in an open landscape",
        "a vintage american car on a desert highway",
        "a woman in a summer dress in a golden field",
        "palm trees and a motel sign at sunset",
        "an american flag waving in the wind",
    ),
    "rubin": (
        "a planet floating in outer space",
        "the earth seen from space",
        "a minimalist abstract sphere on a plain background",
        "a calm ocean horizon with an empty sky",
        "a single stone in a quiet zen garden",
        "a starry sky with planets and moons",
    ),
    "night": (
        "a city street at night with neon lights",
        "a dark moody photo with small lights",
        "a car driving on a road at night",
        "a dark room lit by a single lamp",
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
    "a planet floating in outer space": ("planet", "space", "stars"),
    "the earth seen from space": ("earth space", "planet", "space"),
    "a minimalist abstract sphere on a plain background": ("sphere", "minimal", "moon"),
    "a calm ocean horizon with an empty sky": ("ocean horizon", "calm ocean", "ocean"),
    "a single stone in a quiet zen garden": ("zen", "stone", "nature"),
    "a starry sky with planets and moons": ("stars", "night sky", "moon"),
    "a city street at night with neon lights": ("neon", "city night", "night"),
    "a dark moody photo with small lights": ("city lights", "night", "lights"),
    "a car driving on a road at night": ("night drive", "car night", "night"),
    "a dark room lit by a single lamp": ("lamp", "candle", "night"),
}
STYLE_WEIGHTS = {
    "lana": {"nature": 24, "studio": 5, "americana": 60, "skate": 3, "y2k": 5, "night": 3},
    "rubin": {"nature": 65, "studio": 23, "americana": 9, "skate": 2, "y2k": 1, "night": 0},
    "night": {"nature": 6, "studio": 14, "americana": 22, "skate": 14, "y2k": 9, "night": 35},
}
# Extra grade AFTER the cover LUT; deliberately mild.
GRADES = {
    "lana": ["colortemperature=temperature=5600:mix=0.45",
             "curves=all='0/0.05 0.5/0.52 1/0.95'"],
    "rubin": ["eq=saturation=0.9", "curves=all='0/0.03 1/0.97'"],
    "night": ["colorbalance=bs=0.07:rs=-0.03:bm=0.03",
              "eq=brightness=-0.025:contrast=1.06:gamma=0.96"],
}
DARK_BRIGHTNESS = 0.24
MIN_SCORE = 0.20
MIN_MARGIN = 0.008


def mode() -> str:
    return os.getenv("CARLECOOL_STYLE", "auto").strip().lower() or "auto"


def decide(scores: dict[str, tuple[float, str]], brightness: float | None) -> dict:
    """Pure decision from per-style (best similarity, best prompt) and cover brightness."""
    if brightness is not None and brightness < DARK_BRIGHTNESS:
        return {"style": "night", "basis": f"dark cover (brightness {brightness:.2f})", "prompt": ""}
    if not scores:
        return {"style": None, "basis": "no cover analysis", "prompt": ""}
    ranked = sorted(scores.items(), key=lambda item: -item[1][0])
    (best, (score, prompt)) = ranked[0]
    second = ranked[1][1][0] if len(ranked) > 1 else 0.0
    if score >= MIN_SCORE and score - second >= MIN_MARGIN:
        return {"style": best, "basis": f"cover: {prompt}", "prompt": prompt,
                "score": round(score, 4), "margin": round(score - second, 4)}
    return {"style": None, "basis": "cover unclear → v4 default", "prompt": prompt,
            "score": round(score, 4), "margin": round(score - second, 4)}


def analyze(cover: Path | None, *, override: str = "auto") -> dict:
    """Choose a style for this Reel; never raises (unclear → style None)."""
    chosen = mode() if override in ("", "auto") else override
    if chosen == "off":
        return {"style": None, "basis": "disabled", "prompt": ""}
    if chosen in STYLES:
        return {"style": chosen, "basis": "manual", "prompt": ""}
    if cover is None:
        return {"style": None, "basis": "no cover", "prompt": ""}
    brightness = None
    try:
        from .curation import palette_traits
        brightness = palette_traits(cover)["brightness"]
    except Exception as exc:
        print("Cover palette unavailable for style:", type(exc).__name__)
    scores: dict[str, tuple[float, str]] = {}
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is not None:
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
            scores = {}
    return decide(scores, brightness)


def blended_weights(profile_weights: dict, style: str | None) -> dict:
    if style not in STYLE_WEIGHTS:
        return dict(profile_weights)
    target = STYLE_WEIGHTS[style]
    return {k: int(round(0.5 * int(profile_weights.get(k, 0)) + 0.5 * target[k])) for k in target}


def pace_for(profile_pace: str, style: str | None) -> str:
    return "slow" if style == "rubin" and profile_pace == "medium" else profile_pace


def grade_filters(style: str | None) -> list[str]:
    return list(GRADES.get(style or "", []))


def motif_queries(decision: dict) -> tuple[str, ...]:
    """Motif echo only when the cover was clearly recognised (no guessing on unclear covers)."""
    if not decision.get("style") or decision.get("basis") == "manual":
        return ()
    return MOTIF_QUERIES.get(decision.get("prompt") or "", ())
