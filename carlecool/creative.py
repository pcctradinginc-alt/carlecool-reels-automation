"""CarleCool creative direction: weighted, deterministic licensed-footage curation.

This is an interpretable rule-based director, not an image understanding model.
Only whitelisted controls can affect media processing and GitHub automation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import re

PROFILE_PATH = Path("data/creative-profile.json")
LANES = ("nature", "studio", "americana", "skate", "y2k", "night")
DEFAULT_WEIGHTS = {
    "nature": 28, "studio": 22, "americana": 20,
    "skate": 18, "y2k": 7, "night": 5,
}
PRESETS = {
    "rubin_analog_lana_skate": DEFAULT_WEIGHTS,
    "rubin_lana": {"nature": 40, "studio": 15, "americana": 35, "skate": 6, "y2k": 3, "night": 1},
    "sad_summer_americana": {"nature": 24, "studio": 5, "americana": 60, "skate": 3, "y2k": 5, "night": 3},
    "analog_california": {"nature": 25, "studio": 45, "americana": 18, "skate": 8, "y2k": 3, "night": 1},
    "skate_melancholy": {"nature": 18, "studio": 8, "americana": 26, "skate": 42, "y2k": 5, "night": 1},
    "rubin_calm": {"nature": 65, "studio": 23, "americana": 9, "skate": 2, "y2k": 1, "night": 0},
    "analog_studio": {"nature": 16, "studio": 66, "americana": 12, "skate": 4, "y2k": 2, "night": 0},
    "corecore_hybrid": {"nature": 14, "studio": 15, "americana": 16, "skate": 30, "y2k": 15, "night": 10},
    "minimal_apple_rubin": {"nature": 55, "studio": 32, "americana": 9, "skate": 2, "y2k": 1, "night": 1},
}
CUES = {
    "nature": ("quiet forest sunrise backlight", "river flowing natural light",
               "wind moving trees morning", "warm minimal white room wood floor",
               "ocean window gentle sunlight"),
    "studio": ("vintage drum machine sampler pads hands", "MPC 2000 XL sampler closeup",
               "vinyl record turntable grooves", "analog mixing console knobs",
               "cassette tape reel studio", "guitar wood grain notebook paper",
               "studio musician hands keyboard", "dim recording studio candlelight"),
    "americana": ("California coastal highway sunset", "palm trees golden hour",
                  "vintage roadside motel dusk", "old American diner after dark",
                  "classic car interior road trip", "faded Super 8 summer film",
                  "dusty open highway desert", "old Hollywood empty ballroom"),
    "skate": ("90s California skateboard fisheye low angle",
              "skater asphalt sunset silhouette", "skateboard wheels sidewalk closeup",
              "skatepark natural light documentary", "old camcorder street skate"),
    "y2k": ("Y2K digital camera flash night", "early 2000s camcorder grain",
            "VHS tracking retro tape", "consumer digicam summer"),
    "night": ("night drive coastal road", "purple blue neon city reflection",
              "lonely motel night lights", "city road rain window"),
}
NEGATIVE_RULES = (
    "Avoid glossy influencer or selfie/vlog staging, ringlight aesthetics, "
    "random parties, excessive neon, kitschy cosplay, celebrity likenesses, "
    "watermarks, unauthorized logos, personal data or unlicensed lyrics. "
    "Prefer a static authentic shot over needless camera motion. "
    "Do not claim stock footage literally depicts named equipment unless verified."
)
DELTA = {
    "more_nature": {"nature": 18}, "less_nature": {"nature": -15},
    "more_studio": {"studio": 17}, "more_mpc": {"studio": 23},
    "more_rick_rubin": {"nature": 12, "studio": 10},
    "more_lana": {"americana": 20}, "less_lana": {"americana": -15},
    "more_americana": {"americana": 18},
    "more_melancholy": {"americana": 12, "nature": 8},
    "more_highway": {"americana": 17},
    "more_motel": {"americana": 17},
    "more_palm_sunset": {"americana": 17, "nature": 4},
    "more_old_hollywood": {"americana": 18},
    "less_glamour": {"americana": -6, "nature": 6},
    "more_skate": {"skate": 18}, "less_skate": {"skate": -15},
    "more_y2k": {"y2k": 16}, "less_y2k": {"y2k": -7},
    "less_neon": {"night": -10},
    "more_analog": {"studio": 12, "y2k": 3},
    "more_super8": {"americana": 12, "y2k": 6},
    "no_faces": {"nature": 8, "studio": 4},
}
TEXT_ALIASES = {
    "mehr natur": "more_nature", "weniger natur": "less_nature",
    "mehr studio": "more_studio", "mehr mpc": "more_mpc",
    "rick rubin": "more_rick_rubin", "mehr lana": "more_lana",
    "weniger lana": "less_lana", "mehr americana": "more_americana",
    "mehr melancholie": "more_melancholy", "melancholisch": "more_melancholy",
    "mehr highway": "more_highway", "mehr motel": "more_motel",
    "mehr palmen": "more_palm_sunset", "mehr gegenlicht": "more_nature",
    "mehr sunset": "more_palm_sunset", "mehr skate": "more_skate",
    "weniger skate": "less_skate", "mehr analog": "more_analog",
    "super 8": "more_super8", "mehr y2k": "more_y2k",
    "weniger y2k": "less_y2k", "weniger neon": "less_neon",
    "keine gesichter": "no_faces", "keine menschen": "no_faces",
    "ruhiger": "slower_cuts", "langsamere schnitte": "slower_cuts",
    "schnellere schnitte": "faster_cuts", "mehr dynamik": "faster_cuts",
    "erste 30 sekunden": "first_30_seconds",
    "ki-video": "ai_video", "ki video": "ai_video",
    "mehr ki": "ai_video", "ohne ki": "coverr_only",
}


def default_profile() -> dict:
    return {
        "preset": "rubin_analog_lana_skate",
        "weights": dict(DEFAULT_WEIGHTS),
        "pace": "medium", "analog": 65, "music": "automatic",
        "revision": 0,
        "avoid_faces": False, "ai_video": False,
        "creative_version": 2,
    }


def _normalize(weights: dict) -> dict:
    values = {k: max(0, int(weights.get(k, 0))) for k in LANES}
    total = sum(values.values())
    if not total:
        raise ValueError("At least one creative lane is necessary")
    # Keep integer weights with a deterministic exact 100% total.
    parts = {k: 100 * values[k] // total for k in LANES}
    remainders = sorted(LANES, key=lambda k: (100 * values[k] % total, -LANES.index(k)), reverse=True)
    for k in remainders[:100 - sum(parts.values())]:
        parts[k] += 1
    return parts


def validate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict) or profile.get("preset") not in PRESETS:
        raise ValueError("Unknown creative preset")
    if profile.get("pace") not in ("slow", "medium", "fast"):
        raise ValueError("Pace must be slow, medium or fast")
    if profile.get("music") not in ("automatic", "beginning"):
        raise ValueError("Unsupported music segment")
    analog = profile.get("analog")
    if type(analog) is not int or not 0 <= analog <= 100:
        raise ValueError("Analog intensity must be 0..100")
    if type(profile.get("revision")) is not int or not 0 <= profile["revision"] <= 25:
        raise ValueError("Revision count is invalid")
    if type(profile.get("avoid_faces")) is not bool:
        raise ValueError("Avoid-faces flag must be a boolean")
    if type(profile.get("ai_video", False)) is not bool:
        raise ValueError("AI-video flag must be a boolean")
    raw = profile.get("weights")
    if not isinstance(raw, dict) or set(raw) != set(LANES) or any(
        type(raw[k]) is not int or raw[k] < 0 or raw[k] > 100 for k in LANES
    ):
        raise ValueError("Invalid creative lane weights")
    result = dict(profile)
    result["ai_video"] = profile.get("ai_video", False)
    result["weights"] = _normalize(raw)
    return result


def load_profile(path: Path = PROFILE_PATH) -> dict:
    if not path.is_file():
        return validate_profile(default_profile())
    return validate_profile(json.loads(path.read_text(encoding="utf-8")))


def apply_commands(profile: dict, commands: list[str]) -> dict:
    out = dict(validate_profile(profile))
    out["weights"] = dict(out["weights"])
    for name in commands:
        if name.startswith("preset_") and name[7:] in PRESETS:
            preset = name[7:]
            out["preset"] = preset
            out["weights"] = dict(PRESETS[preset])
        elif name in DELTA:
            for k, d in DELTA[name].items():
                out["weights"][k] = max(0, out["weights"][k] + d)
            if name in ("more_analog", "more_super8"):
                out["analog"] = min(100, out["analog"] + 15)
            if name == "no_faces":
                out["avoid_faces"] = True
        elif name in ("ai_video", "coverr_only"):
            out["ai_video"] = name == "ai_video"
        elif name in ("slower_cuts", "faster_cuts"):
            out["pace"] = "slow" if name == "slower_cuts" else "fast"
        elif name == "first_30_seconds":
            out["music"] = "beginning"
        else:
            raise ValueError("Unsupported creative command: " + name)
        out["weights"] = _normalize(out["weights"])
    return validate_profile(out)


def interpret_revision(comment: str) -> list[str]:
    """Whitelisted commands and limited German keyword intent, not an LLM."""
    if not comment.startswith("/revise "):
        raise ValueError("Comment must begin with /revise followed by instructions")
    raw = comment[8:].strip().lower()
    if not raw or len(raw) > 500 or "\n" in raw:
        raise ValueError("Revision instructions must be 1..500 characters on one line")
    pieces = [p.strip() for p in raw.replace(",", " ").split()]
    if len(pieces) == 1 and (pieces[0] in DELTA or pieces[0] in
                              ("slower_cuts", "faster_cuts", "first_30_seconds", "ai_video", "coverr_only")
                              or pieces[0].startswith("preset_") and pieces[0][7:] in PRESETS):
        return pieces
    found = []
    for phrase, name in TEXT_ALIASES.items():
        if phrase in raw and name not in found:
            found.append(name)
    if not found:
        raise ValueError("No supported direction found. Use e.g. /revise mehr natur, weniger skate")
    return found[:5]


def choose_shots(profile: dict, *, track_id: str, mood: str, energy: float, limit=3,
                 run_key: str = "") -> list[str]:
    """Weighted without-replacement lane sampling, max three Coverr API searches."""
    p = validate_profile(profile)
    if not 1 <= limit <= 3:
        raise ValueError("Coverr Free can search at most 3 lanes")
    weights = dict(p["weights"])
    from .quality_learning import load as load_learning, adjusted_weights
    weights = adjusted_weights(weights, load_learning())
    if mood == "calm":
        weights["nature"] += 8
        weights["studio"] += 5
    if energy >= .65:
        weights["skate"] += 8
    if p["avoid_faces"]:
        weights["nature"] += 15
    random_seed = hashlib.sha256(
        f"{track_id}|{run_key}|{p['revision']}|{p['preset']}|{json.dumps(weights, sort_keys=True)}".encode()
    ).digest()
    rng = random.Random(int.from_bytes(random_seed, "big"))
    selected = []
    available = [k for k in LANES if weights[k] > 0]
    for _ in range(min(limit, len(available))):
        lane = rng.choices(available, weights=[weights[k] for k in available], k=1)[0]
        available.remove(lane)
        phrases = CUES[lane]
        chosen = phrases[rng.randrange(len(phrases))]
        selected.append(chosen)
    return selected
