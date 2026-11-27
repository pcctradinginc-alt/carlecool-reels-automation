"""U.S. National Archives Catalog as a footage source (owner, 27 Nov: "API sauber integrieren";
key limit 10,000 calls per month — "so anpassen, dass jeden Tag ein Video generiert werden kann").

* Search: GET https://catalog.archives.gov/api/v2/records/search (header `x-api-key`) with
  `typeOfMaterials=Moving Images`, `availableOnline=true`, `limit`, `page` — parameter names
  from the official OpenAPI spec (/api/v2/swagger.json). One search = one API call.
* Rights: only records whose `useRestriction.status` AND `accessRestriction.status` are
  exactly "Unrestricted"; only MP4 digital objects. Titles about presidents / politicians /
  war / news are skipped (no celebrity likeness, no political or violent content).
* Media: the MP4 is streamed from catalog.archives.gov (range requests, not an API call);
  only the checked 9 s segment is cut — never the whole film. The same CLIP content gate as
  the Prelinger archive decides (best offset + every frame of the cut), with prompts per
  director (Lana: sunny summers, coast, sailing; Night: city lights, neon, night streets).
* Budget: every call is recorded in data/provider-usage.json ("nara" events). A run may
  use at most  min(RUN_CAP, (90 % of the monthly limit − used this month) ÷ days left ÷ runs
  per day)  calls, so the month can never run dry and every day keeps its Reels. A normal
  run needs 3–6 calls (~300 per month).
* Attribution required by NARA's API terms is part of every clip's licence record.
Without `NARA_API_KEY` the source is simply skipped. Never raises.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import calendar
import json
import os
from pathlib import Path
import subprocess

import requests

API = "https://catalog.archives.gov/api/v2/records/search"
MEDIA_HOST = "catalog.archives.gov"
from .budgets import NARA_MONTHLY as MONTHLY_LIMIT, NARA_PER_RUN
RESERVE = 0.10            # never plan with the last 10 % of the month
RUNS_PER_DAY = 2          # the guard allows two Reels per Berlin day
RUN_CAP = NARA_PER_RUN    # hard cap per run (budgets.py)
PAGE_SIZE = 50
KEEP = timedelta(days=40)
RUN_CALLS = 0             # API calls of this process (recorded by main.record_provider_usage)
ATTRIBUTION = ("This product uses the National Archives Catalog API but is not endorsed or "
               "certified by the National Archives and Records Administration.")
LICENCE = "Public domain – U.S. National Archives (use restriction: Unrestricted)"
EXCLUDE = ("president", "kennedy", "jfk", "onassis", "nixon", "eisenhower", "truman", "roosevelt",
           "reagan", "johnson", "carter", "ford", "bush", "clinton", "senator", "congress",
           "white house", "speech", "press conference", "briefing", "news", "interview", "hearing",
           "war", "army", "navy", "air force", "marine", "military", "combat", "bomb", "atomic",
           "nuclear", "weapon", "missile", "soldier", "veteran", "vietnam", "korea", "nazi",
           "propaganda", "crime", "police", "prison", "accident", "disaster", "fire", "riot",
           "funeral", "hospital", "surgery", "disease", "drug", "training film", "lecture")
DEFAULT_QUERIES = {
    "lana": ("summer beach", "sailing", "regatta", "boardwalk", "amusement park", "cape cod",
             "tennis", "horse show", "parade", "picnic", "swimming", "yacht"),
    "night": ("new york night", "times square", "neon signs", "city lights", "brooklyn bridge",
              "baseball game", "subway", "night traffic", "harlem", "coney island"),
}
POSITIVE = {
    "lana": ("a sunny vintage color film of a beach, sailing boats or the sea",
             "an old color film of an american summer day, a boardwalk or a small town",
             "a vintage film of people at a summer fair, a regatta or a tennis court"),
    "night": ("an old film of a city street at night with neon signs and lights",
              "a vintage film of new york at night with car lights",
              "a black and white film of a city skyline or a bridge at night"),
}
NEGATIVE = {
    "lana": ("a title card with large text", "a person talking to the camera", "soldiers or military",
             "an office, a factory or a laboratory", "a map, a chart or a diagram", "a black or blank screen",
             "a politician giving a speech"),
    "night": ("a sunny daytime scene", "a title card with large text", "a person talking to the camera",
              "soldiers or military", "an office, a factory or a laboratory", "a black or blank screen",
              "a politician giving a speech"),
}


def api_key() -> str:
    return os.getenv("NARA_API_KEY", "").strip()


# ---------------------------------------------------------------- budget

def _events(data: dict, now: datetime) -> list[dict]:
    out = []
    for e in (data.get("nara") or {}).get("events") or []:
        try:
            at = datetime.fromisoformat(str(e.get("at")))
        except (TypeError, ValueError):
            continue
        if now - at <= KEEP:
            out.append(dict(e, _at=at))
    return out


def used_this_month(data: dict, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return sum(int(e.get("requests") or 0) for e in _events(data, now)
               if e["_at"].year == now.year and e["_at"].month == now.month)


def run_budget(data: dict | None = None, now: datetime | None = None) -> int:
    """API calls this run may use (0 = skip)."""
    from .providers import load
    now = now or datetime.now(timezone.utc)
    data = load() if data is None else data
    left = int(MONTHLY_LIMIT * (1 - RESERVE)) - used_this_month(data, now)
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day + 1
    return max(0, min(RUN_CAP, left // max(1, days_left * RUNS_PER_DAY)))


def record(requests_used: int, run_id: str | None, path: Path | None = None,
           now: datetime | None = None) -> dict:
    """Append this run's NARA calls to data/provider-usage.json (kept 40 days)."""
    from . import providers
    path = path or providers.PATH
    now = now or datetime.now(timezone.utc)
    data = providers.load(path)
    events = [{k: v for k, v in e.items() if k != "_at"} for e in _events(data, now)]
    if requests_used:
        events.append({"at": now.isoformat(timespec="seconds"), "run": str(run_id or ""),
                       "requests": int(requests_used)})
    data["nara"] = {"monthly_limit": MONTHLY_LIMIT, "events": events}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return data


# ---------------------------------------------------------------- search

def _blocked_title(title: str) -> bool:
    import re
    t = title.lower()
    return any(re.search(r"\b" + re.escape(w) + r"\b", t) for w in EXCLUDE)


def parse_hits(payload: dict) -> list[dict]:
    """Usable records of one search response: unrestricted, with an MP4, safe title."""
    body = payload.get("body", payload) if isinstance(payload, dict) else {}
    out = []
    for hit in ((body.get("hits") or {}).get("hits") or []):
        rec = (hit.get("_source") or {}).get("record") or {}
        if (rec.get("useRestriction") or {}).get("status") != "Unrestricted":
            continue
        if (rec.get("accessRestriction") or {}).get("status") != "Unrestricted":
            continue
        title = str(rec.get("title") or "").strip()
        if not title or _blocked_title(title):
            continue
        mp4 = next((o for o in rec.get("digitalObjects") or []
                    if str(o.get("objectFilename") or o.get("objectUrl") or "").lower().endswith(".mp4")
                    and str(o.get("objectUrl") or "").startswith(f"https://{MEDIA_HOST}/")), None)
        if mp4 is None:
            continue
        na_id = str(rec.get("naId") or hit.get("_id") or "")
        if not na_id.isdigit():
            continue
        dates = rec.get("productionDates") or rec.get("coverageDates") or []
        year = next((d.get("year") for d in dates if isinstance(d, dict) and d.get("year")), None)
        out.append({"id": f"nara-{na_id}", "naId": na_id, "title": title, "url": mp4["objectUrl"],
                    "year": year, "page": f"https://catalog.archives.gov/id/{na_id}"})
    return out


class Searcher:
    """Counts every API call against this run's budget."""

    def __init__(self, budget: int, session=None):
        self.budget = budget
        self.used = 0
        self.session = session or requests.Session()

    def search(self, query: str, page: int = 1) -> list[dict]:
        if self.used >= self.budget or not api_key():
            return []
        self.used += 1
        r = self.session.get(API, params={"q": query, "typeOfMaterials": "Moving Images", "availableOnline": "true",
                                          "limit": PAGE_SIZE, "page": page},
                             headers={"x-api-key": api_key(), "Content-Type": "application/json"}, timeout=30)
        if r.status_code in (401, 403, 429):
            print(f"NARA API refused ({r.status_code}); source skipped for this run")
            self.budget = self.used
            return []
        r.raise_for_status()
        return parse_hits(r.json())


def queries_for(director: str | None) -> tuple[str, ...]:
    from . import directors
    d = directors.get(director) or {}
    return tuple(d.get("nara_queries") or DEFAULT_QUERIES.get(director or "", DEFAULT_QUERIES["lana"]))


# ---------------------------------------------------------------- footage

def fetch_nara(director: str | None, exclude: set[str], workdir: Path, *, run_key: str = "",
               max_clips: int = 2, session=None, budget: int | None = None) -> tuple[list, int]:
    """(clips, API calls used). Checked 9 s segments of unrestricted NARA films."""
    from . import archives
    from .video import Video
    if not api_key() or max_clips <= 0:
        return [], 0
    world = "night" if director == "night" or (director or "").startswith("night") else "lana"
    archives.POSITIVE.setdefault(f"nara_{world}", POSITIVE[world])
    archives.NEGATIVE.setdefault(f"nara_{world}", NEGATIVE[world])
    searcher = Searcher(run_budget() if budget is None else budget, session=session)
    if searcher.budget <= 0:
        print("NARA: monthly budget reserved for the remaining days — skipped this run")
        return [], 0
    import hashlib
    queries = list(queries_for(director))
    start = int.from_bytes(hashlib.sha256(f"{run_key}|nara".encode()).digest()[:1], "big") % len(queries)
    queries = queries[start:] + queries[:start]  # documented A/B-free rotation: other films each run
    found = []
    for query in queries:
        if len(found) >= max_clips or searcher.used >= searcher.budget:
            break
        try:
            items = [i for i in searcher.search(query) if i["id"] not in exclude]
        except (requests.RequestException, ValueError) as exc:
            print(f"NARA search '{query}' unavailable: {type(exc).__name__}")
            continue
        for item in items[:4]:
            if len(found) >= max_clips:
                break
            try:
                duration, _w, _h = archives.remote_info(item["url"])
                if duration < archives.SEGMENT_SECONDS + 5:
                    continue
                at, margin = archives.best_offset(item["url"], duration, f"nara_{world}", f"{run_key}|{item['id']}")
                if at is None:
                    print(f"NARA clip rejected by content check: {item['id']} ({margin})")
                    continue
                path = archives.cut_segment(item["url"], at, workdir / f"nara_{len(found):02d}.mp4")
                if not archives.segment_ok(path, f"nara_{world}"):
                    print(f"NARA clip rejected after cut (mixed content): {item['id']}")
                    path.unlink(missing_ok=True)
                    continue
                found.append(Video(item["id"], "nara", path=str(path), title=item["title"],
                                   creator_name="U.S. National Archives", creator_url=item["page"],
                                   query=query, page_url=item["page"], licence=f"{LICENCE}. {ATTRIBUTION}",
                                   licence_url=item["page"], duration=archives.SEGMENT_SECONDS))
                exclude.add(item["id"])
                print(f"NARA clip: {item['id']} '{item['title'][:50]}' @ {at:.0f}s")
            except (requests.RequestException, ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
                print(f"NARA clip skipped: {item.get('id')}: {type(exc).__name__}")
    global RUN_CALLS
    RUN_CALLS += searcher.used
    print(f"NARA: {len(found)} clips, {searcher.used} API calls (run budget {searcher.budget})")
    return found, searcher.used
