"""Conservative, transparent learning from *explicit owner revision commands*.

No invented watch-time, hidden training, external services or user profiles.
A signal only means the owner requested more/less of one visual lane; it does
not measure virality, engagement or causal improvement.
"""
from __future__ import annotations
import json
from pathlib import Path

PATH = Path("data/creative-learning.json")
LANES = ("nature", "studio", "americana", "skate", "y2k", "night")
DELTA_MAP = {
    "more_nature": ("nature", 1), "less_nature": ("nature", -1),
    "more_studio": ("studio", 1), "more_mpc": ("studio", 1),
    "more_rick_rubin": ("nature", 1), "more_lana": ("americana", 1),
    "less_lana": ("americana", -1), "more_americana": ("americana", 1),
    "more_melancholy": ("americana", 1), "more_highway": ("americana", 1),
    "more_motel": ("americana", 1), "more_palm_sunset": ("americana", 1),
    "more_skate": ("skate", 1), "less_skate": ("skate", -1),
    "more_y2k": ("y2k", 1), "less_y2k": ("y2k", -1),
    "less_neon": ("night", -1), "more_analog": ("studio", 1),
    "more_super8": ("americana", 1),
}


def initial() -> dict:
    return {"version": 1, "observations": 0,
            "preferences": {lane: 0 for lane in LANES}}


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Invalid creative learning file")
    if type(data.get("observations")) is not int or not 0 <= data["observations"] <= 100000:
        raise ValueError("Invalid observation count")
    prefs = data.get("preferences")
    if (not isinstance(prefs, dict) or set(prefs) != set(LANES)
            or any(type(prefs[k]) is not int or not -8 <= prefs[k] <= 8 for k in LANES)):
        raise ValueError("Invalid bounded preference scores")
    return data


def load(path: Path = PATH) -> dict:
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return initial()


def observe(data: dict, commands: list[str]) -> dict:
    existing = validate(data)
    prefs = dict(existing["preferences"])
    changes = {}
    for command in commands:
        if command in DELTA_MAP:
            lane, direction = DELTA_MAP[command]
            changes[lane] = direction
    for lane, direction in changes.items():
        prefs[lane] = max(-8, min(8, prefs[lane] + direction))
    return {"version": 1,
            "observations": min(100000, existing["observations"] + int(bool(changes))),
            "preferences": prefs}


def adjusted_weights(weights: dict, data: dict) -> dict:
    prefs = validate(data)["preferences"]
    # A learned preference cannot overwhelm artist-selected profile weights.
    return {k: max(0, int(weights[k]) + prefs[k]) for k in LANES}
