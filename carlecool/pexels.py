"""Pexels videos: the portrait (9:16) footage source.

Coverr's free catalogue returned 0 portrait clips in 200+ live hits; Pexels offers an
`orientation=portrait` filter. Free API (200 requests/hour). Pexels licence: free use,
attribution appreciated; API guidelines ask for a visible Pexels link and creator credit,
which the caption provides ("Video by <name> on Pexels").
Active only when the PEXELS_API_KEY secret is set.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import requests

from .video import Video, query_ladder

API = "https://api.pexels.com/v1/videos/search"


def configured() -> bool:
    return bool(os.getenv("PEXELS_API_KEY", "").strip())


def _best_file(files: list, *, landscape=False) -> dict | None:
    """Portrait MP4 closest to 1080×1920 (avoid 4K downloads, avoid < 720p)."""
    usable = []
    for f in files or []:
        try:
            w, h = int(f.get("width") or 0), int(f.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if f.get("file_type") != "video/mp4" or not f.get("link") or (min(w, h) < 720 if landscape else (h <= w or h < 1280)):
            continue
        usable.append((abs((w if landscape else h) - 1920), -h, f))
    return min(usable, key=lambda x: (x[0], x[1]))[2] if usable else None


def _credit(user: dict) -> tuple[str, str]:
    name = str((user or {}).get("name") or "").strip()[:100]
    url = str((user or {}).get("url") or "").strip()
    parsed = urlparse(url)
    if not name or parsed.scheme != "https" or parsed.hostname not in ("www.pexels.com", "pexels.com"):
        return name, ""
    return name, url


def search_pexels(key: str, keywords: list[str], recent: set[str], *, session=None,
                  per_query: int = 30, per_lane_minimum: int = 6, wanted: int = 18) -> list[Video]:
    """Portrait-only search per lane: full phrase, then its core words (max 6 requests)."""
    if not key:
        return []
    session = session or requests.Session()
    seen: set[str] = set()
    lanes: list[list[Video]] = []
    stopped = False
    from .video import allow_landscape
    for editorial in keywords[:6]:
        if stopped:
            break
        lane: list[Video] = []
        for attempt, (query, orientation) in enumerate([(q, "portrait") for q in query_ladder(editorial)[:2]] + ([(query_ladder(editorial)[0], "landscape")] if allow_landscape() else [])):
            if attempt and len(lane) >= per_lane_minimum:
                break
            try:
                r = session.get(API, headers={"Authorization": key}, timeout=30,
                                params={"query": query, "orientation": orientation, "size": "medium",
                                        "per_page": per_query})
                r.raise_for_status()
                videos = r.json().get("videos", [])
            except (requests.RequestException, ValueError) as exc:
                print(f"Pexels unavailable ({type(exc).__name__}); retaining earlier candidates")
                stopped = True
                break
            print(f"Pexels '{query}': {len(videos)} portrait hits")
            for item in videos:
                vid = f"px-{item.get('id')}"
                if not item.get("id") or vid in seen or vid in recent:
                    continue
                best = _best_file(item.get("video_files"), landscape=orientation == "landscape")
                if best is None:
                    continue
                seen.add(vid)
                name, url = _credit(item.get("user") or {})
                lane.append(Video(vid, "pexels", url=str(best["link"]), title=str(item.get("url") or ""),
                                  vertical=int(best.get("height") or 0) > int(best.get("width") or 0), page_url=str(item.get("url") or ""), creator_name=name, creator_url=url, query=editorial,
                                  thumb_url=str(item.get("image") or ""),
                                  duration=float(item.get("duration") or 0),
                                  width=int(best.get("width") or 0), height=int(best.get("height") or 0)))
        lanes.append(lane)
    found: list[Video] = []
    while len(found) < wanted and any(lanes):
        lanes = [lane for lane in lanes if lane]
        for lane in lanes:
            if lane and len(found) < wanted:
                found.append(lane.pop(0))
    return found
