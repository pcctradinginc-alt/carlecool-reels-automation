"""Durable, fail-closed publication journal committed to the repository."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

from .soundcloud import Track

STATE_PATH = Path("data/state.json")


def load_state(path: Path = STATE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pick_track(tracks: list[Track], state: dict, cooldown_days: int = 19, now=None) -> Track:
    if state.get("pending"):
        raise RuntimeError("Unresolved pending Instagram publication: manual reconciliation required")
    now = now or datetime.now(timezone.utc)
    published = state.get("published", [])
    # An archived uncertain attempt still deserves a cooldown. It must not be
    # treated as proof of publication, nor picked again immediately.
    recent_attempts = published + state.get("reconciled", [])
    eligible = []
    for track in tracks:
        dates = [datetime.fromisoformat(x["at"]) for x in recent_attempts if x.get("track_id") == track.id]
        last = max(dates) if dates else None
        if last and (now - last) < timedelta(days=cooldown_days):
            continue
        eligible.append((last or datetime(2000, 1, 1, tzinfo=timezone.utc), track))
    if not eligible:
        raise RuntimeError("No tracks are eligible after repost cooldown; skipping rather than double posting")
    return min(eligible, key=lambda x: x[0])[1]


def is_already_attempted_sha(state: dict, sha256: str) -> bool:
    """Block re-upload of byte-identical media from published or archived attempts.

    Historical 'reconciled' attempts do not imply actual publication. Their
    uncertainty is exactly why blind retries of identical media are disallowed.
    """
    return any(x.get("sha256") == sha256
               for section in ("published", "reconciled")
               for x in state.get(section, []))


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def commit_state(message: str) -> None:
    """Persist intent before external publishing to make ambiguous results fail closed."""
    def git(*args):
        subprocess.run(["git", *args], check=True, stdout=subprocess.DEVNULL)
    git("add", "data/state.json")
    git("commit", "-m", message)
    git("push", "origin", "HEAD:main")
