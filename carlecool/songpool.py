"""Which songs the daily Reel may pick from (data/song-pool.json).

mode "playlist": only the tracks of one of the owner's SoundCloud sets (EP/album), e.g.
                 "MPC2000XL/ GHOST NOTES//". Resolved live via the SoundCloud API, so
                 tracks added to the set later are picked up automatically.
mode "all":      the 20 newest public uploads (previous behaviour).
Repo variable / env CARLECOOL_SONG_POOL=all overrides the file without a commit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

PATH = Path("data/song-pool.json")


def load(path: Path = PATH) -> dict:
    if os.getenv("CARLECOOL_SONG_POOL", "").strip().lower() == "all":
        return {"mode": "all"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"mode": "all"}
    if data.get("mode") == "playlist":
        url = str(data.get("playlist_url") or "")
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.hostname == "soundcloud.com" and "/sets/" in parsed.path:
            return {"mode": "playlist", "playlist_url": url, "label": str(data.get("label") or "")}
        raise ValueError("data/song-pool.json: playlist_url must be a https://soundcloud.com/<user>/sets/<name> link")
    return {"mode": "all"}
