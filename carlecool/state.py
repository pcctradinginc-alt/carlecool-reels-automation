"""Durable, fail-closed publication journal committed to the repository."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from .soundcloud import Track

STATE_PATH = Path("data/state.json")


# Text of data/state.json as last known to match main (set on load, updated per write).
_synced: str | None = None


def load_state(path: Path = STATE_PATH) -> dict:
    global _synced
    text = path.read_text(encoding="utf-8")
    if path == STATE_PATH:
        _synced = text
    return json.loads(text)


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


def commit_state(message: str, *, request=None, retries: int = 4) -> None:
    """Persist the journal to main via the GitHub contents API (no `git push`).

    Why: a publish run takes minutes (Gmail fetch, upload, waiting for TikTok). Any
    other commit on main in between (preview history, code) made the old `git push`
    fail with "non-fast-forward" — possibly AFTER a post went live, leaving the journal
    stuck on "pending". The contents API only conflicts if data/state.json ITSELF
    changed; then we refuse to overwrite someone else's journal edit (fail closed).
    """
    global _synced
    import requests
    if request is None:
        from .review import github_request as request
    desired = STATE_PATH.read_text(encoding="utf-8")
    if _synced is None:
        raise RuntimeError("Journal was not loaded in this run; refusing to write blindly")
    for attempt in range(retries):
        current = request("GET", "contents/data/state.json?ref=main")
        remote = base64.b64decode(current["content"]).decode("utf-8")
        if remote == desired:
            _synced = desired
            return
        if remote != _synced:
            raise RuntimeError("data/state.json was changed on main during this run; "
                               "not overwriting it. Reconcile the journal manually.")
        try:
            request("PUT", "contents/data/state.json", json_body={
                "message": message, "branch": "main", "sha": current["sha"],
                "content": base64.b64encode(desired.encode("utf-8")).decode("ascii"),
            })
            _synced = desired
            return
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status not in (409, 422) or attempt == retries - 1:
                raise
            time.sleep(min(2 ** attempt, 4))
    raise RuntimeError("Journal write failed after concurrent updates")
