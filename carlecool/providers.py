"""Persistent provider limits across runs (owner, 26 Nov — "ein gesperrter Anbieter darf
nicht das gesamte Produktionssystem lahmlegen").

Coverr allows ~50 API requests per hour. Each run already stops itself at 35 requests
(video.COVERR_MAX_REQUESTS), but runs did not know about each other: on 25 Nov five runs
in a row were stopped by HTTP 403 because the previous run had used the hour up.

data/provider-usage.json keeps, per run, how many Coverr requests were made and whether
Coverr answered 403/429. Before searching, main.py asks `coverr_plan()`:
* enough budget in the last hour → go, with this run's budget capped to what is left;
* not enough / blocked recently → wait (up to MAX_WAIT = 60 min) until the hour has passed;
* longer than that → run without Coverr (archive, Wikimedia, Pexels, AI); the quality
  gate still decides (fail closed) and the second daily slot retries later.
The render step writes the file; a workflow step commits it even when the run fails.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

PATH = Path("data/provider-usage.json")
WINDOW = timedelta(hours=1)
HOURLY_LIMIT = 50          # Coverr's documented allowance
MIN_FOR_A_REEL = 20        # search lanes + fallbacks + signature roles + download stats
MAX_WAIT = timedelta(minutes=60)  # public repo: runner minutes are free; job timeout 90 min
KEEP = timedelta(days=2)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load(path: Path = PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _events(data: dict, now: datetime) -> list[dict]:
    out = []
    for e in (data.get("coverr") or {}).get("events") or []:
        try:
            at = datetime.fromisoformat(str(e.get("at")))
        except (TypeError, ValueError):
            continue
        if now - at <= KEEP:
            out.append(dict(e, _at=at))
    return out


def coverr_plan(data: dict | None = None, now: datetime | None = None) -> dict:
    """{"action": "go"|"wait"|"skip", "budget": int, "wait_s": int, "reason": str}."""
    now = now or _now()
    events = _events(load() if data is None else data, now)
    recent = [e for e in events if now - e["_at"] < WINDOW]
    used = sum(int(e.get("requests") or 0) for e in recent)
    blocks = [e["_at"] for e in recent if e.get("blocked")]
    remaining = max(0, HOURLY_LIMIT - used)
    if not blocks and remaining >= MIN_FOR_A_REEL:
        return {"action": "go", "budget": remaining - 2, "wait_s": 0,
                "reason": f"{used} Coverr requests in the last hour, {remaining} left"}
    reason = (f"Coverr blocked at {max(blocks):%H:%M} UTC" if blocks
              else f"{used} Coverr requests in the last hour")
    earliest = max(blocks) + WINDOW if blocks else now
    # the hour frees up as earlier requests fall out of it: first moment with enough budget
    for t in sorted({earliest} | {e["_at"] + WINDOW for e in recent if e["_at"] + WINDOW >= earliest}):
        still = sum(int(e.get("requests") or 0) for e in recent if e["_at"] > t - WINDOW)
        budget = HOURLY_LIMIT - still - 2
        if budget >= MIN_FOR_A_REEL:
            wait = t - now
            if wait <= MAX_WAIT:
                return {"action": "wait", "budget": budget,
                        "wait_s": max(0, int(wait.total_seconds()) + 30), "reason": reason}
            break
    return {"action": "skip", "budget": 0, "wait_s": 0, "reason": reason}


def record(requests: int, blocked: int | None, run_id: str | None, path: Path = PATH,
           now: datetime | None = None) -> dict:
    """Append this run's Coverr usage (kept two days) and write the file locally."""
    now = now or _now()
    data = load(path)
    events = [{k: v for k, v in e.items() if k != "_at"} for e in _events(data, now)]
    events.append({"at": now.isoformat(timespec="seconds"), "run": str(run_id or ""),
                   "requests": int(requests), "blocked": int(blocked) if blocked else None})
    data = dict(data, version=1, coverr={"hourly_limit": HOURLY_LIMIT, "events": events})  # keeps "nara"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return data


def _union(a: list, b: list) -> list:
    seen, out = set(), []
    for e in (a or []) + (b or []):
        key = (e.get("at"), str(e.get("run")))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return sorted(out, key=lambda e: str(e.get("at")))


def merge(remote: dict, local: dict) -> dict:
    """Union of both files' events per provider (another run may have written main meanwhile)."""
    out = {"version": 1, "coverr": {"hourly_limit": HOURLY_LIMIT,
                                    "events": _union((remote.get("coverr") or {}).get("events"),
                                                     (local.get("coverr") or {}).get("events"))}}
    nara = _union((remote.get("nara") or {}).get("events"), (local.get("nara") or {}).get("events"))
    if nara:
        out["nara"] = dict(local.get("nara") or remote.get("nara") or {}, events=nara)
    return out


def main() -> int:
    """`python -m carlecool.providers` (workflow, always): commit the usage file."""
    if not PATH.is_file() or os.getenv("GITHUB_ACTIONS") != "true":
        print("Provider usage: nothing to record")
        return 0
    from .performance import commit_json
    try:
        import base64
        from .review import github_request
        try:
            item = github_request("GET", f"contents/{PATH.as_posix()}?ref=main")
            remote = json.loads(base64.b64decode(item["content"]).decode("utf-8"))
            PATH.write_text(json.dumps(merge(remote, load()), indent=1) + "\n", encoding="utf-8")
        except Exception as exc:  # 404 / network: commit this run's file as it is
            print("Provider usage: no merge with main:", type(exc).__name__)
        commit_json(PATH, "providers: record Coverr usage of this run [skip ci]")
        print("Provider usage recorded")
    except Exception as exc:  # never fail the run for bookkeeping
        print("Warning: provider usage not stored:", type(exc).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
