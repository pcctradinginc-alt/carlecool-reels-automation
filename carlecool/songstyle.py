"""Owner's style choice per song: `/revise stil rubin` on a Reel of a song is remembered.

data/song-styles.json maps SoundCloud track id → "lana" | "rubin" | "night". Every later
Reel of that song uses it (manual beats cover and music detection); `/revise stil auto`
forgets it again. Only public style names are stored.
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path("data/song-styles.json")
ALLOWED = ("lana", "rubin", "night")


def load(path: Path = PATH) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str) and v in ALLOWED and str(k).isdigit()}


def remember(track_id: str, style: str, path: Path = PATH) -> dict[str, str]:
    """Store (or with style "auto" forget) the owner's choice; returns the new mapping."""
    track_id = str(track_id)
    if not track_id.isdigit():
        raise ValueError("Invalid track id")
    data = load(path)
    if style == "auto":
        data.pop(track_id, None)
    elif style in ALLOWED:
        data[track_id] = style
    else:
        raise ValueError("Unknown style")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), indent=2) + "\n", encoding="utf-8")
    return data


def for_track(track_id: str, path: Path = PATH) -> str | None:
    return load(path).get(str(track_id))
