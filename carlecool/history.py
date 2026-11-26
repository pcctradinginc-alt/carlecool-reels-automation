"""Balanced, random daily rotation across the artist's current 20 public tracks.

The repository persists only review metadata after Gmail accepts each email.
No video/audio bytes or email addresses are stored here.
"""
from __future__ import annotations

import base64
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import time

import requests

from .soundcloud import Track

HISTORY_PATH = Path("data/preview-history.json")
HISTORY_LIMIT = 600


def _entries(doc: dict) -> list[dict]:
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ValueError("Unrecognized preview history version")
    entries = doc.get("previews")
    if not isinstance(entries, list) or any(not isinstance(x, dict) for x in entries):
        raise ValueError("Invalid preview history entries")
    return entries


def load_preview_history(path: Path = HISTORY_PATH) -> list[dict]:
    """Reject broken metadata rather than accidentally resetting rotation."""
    return _entries(json.loads(path.read_text(encoding="utf-8")))


def pick_preview_track(tracks: list[Track], previews: list[dict], *, rng=None) -> Track:
    """Uniform random choice among least-used tracks in the current rolling top 20.

    For a stable catalog of 20 tracks, the selection counts differ by at most
    one after a complete rotation. When newer uploads arrive, unused newcomers
    are naturally prioritized. Owner-requested revisions do not inflate counts.
    """
    current = list(tracks[:20])
    if not current:
        raise RuntimeError("No eligible public SoundCloud tracks")
    if len({t.id for t in current}) != len(current):
        raise ValueError("SoundCloud returned duplicate track IDs")
    counts = Counter(str(p.get("track_id")) for p in previews
                     if p.get("kind") != "revision" and p.get("track_id") is not None)
    least = min(counts[t.id] for t in current)
    pool = [t for t in current if counts[t.id] == least]
    return (rng or secrets.SystemRandom()).choice(pool)


def recent_video_ids(previews: list[dict], *, limit: int = 6) -> set[str]:
    """Exclude recently emailed stock clips, not just published ones."""
    return {str(v) for entry in previews[-limit:] for v in entry.get("video_ids", [])
            if isinstance(v, str) and not v.startswith("hf-ltx23-")}


def record_preview_delivery(metadata: dict, *, run_id: int, kind: str = "daily",
                            token: str, repo: str, session=None) -> bool:
    """Optimistically append once to GitHub after SMTP delivery succeeds.

    A duplicate run ID is a no-op; a concurrent write is re-read and retried.
    Raise on write failure so the Actions run never reports false durability.
    """
    if not token or not repo or not repo.count("/") == 1:
        raise RuntimeError("GitHub write access required for durable preview history")
    if kind not in ("daily", "test", "revision"):
        raise ValueError("Unknown preview kind")
    if not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("GitHub run ID must be positive")
    new_entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "run_id": run_id,
        "track_id": str(metadata["track_id"]),
        "video_ids": [str(v) for v in metadata.get("video_ids", [])],
        "sha256": str(metadata["sha256"]),
    }
    facts = metadata.get("reel_facts") or {}
    if facts.get("style") in ("lana", "rubin"):  # style rotation (owner, 25 Nov)
        new_entry["style"] = "night" if facts.get("variant") == "night" else facts["style"]
        if facts.get("theme"):
            new_entry["theme"] = facts["theme"]  # theme rotation (owner, 26 Nov)
    if metadata.get("length_bucket") in ("short", "long"):
        new_entry["length_bucket"] = metadata["length_bucket"]  # length A/B test per song
    # Only the canonical repository-relative path is used; no user-controlled URL.
    from .review import github_request
    for attempt in range(4):
        current = github_request("GET", "contents/data/preview-history.json?ref=main",
                                 token=token, repo=repo, session=session)
        document = json.loads(base64.b64decode(current["content"]).decode("utf-8"))
        entries = _entries(document)
        if any(x.get("run_id") == run_id for x in entries):
            return False
        # Keep full rounds of metadata for long-term balancing.
        updated = {"version": 1, "previews": (entries + [new_entry])[-HISTORY_LIMIT:]}
        payload = {
            "message": f"history: record private preview run {run_id}",
            "content": base64.b64encode((json.dumps(updated, ensure_ascii=False, indent=2)
                                          + "\n").encode("utf-8")).decode("ascii"),
            "sha": current["sha"],
            "branch": "main",
        }
        try:
            github_request("PUT", "contents/data/preview-history.json",
                           json_body=payload, token=token, repo=repo, session=session)
            return True
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in (409, 422) or attempt == 3:
                raise
            time.sleep(min(2 ** attempt, 4))
    raise RuntimeError("History update failed after concurrent writes")
