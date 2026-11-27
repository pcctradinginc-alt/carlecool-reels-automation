"""Coverr footage discovery and a private, license-checked fallback library."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
import re
from pathlib import Path
import socket
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class Video:
    id: str
    source: str
    url: str | None = None
    path: str | None = None
    title: str = ""
    s3_key: str | None = None
    views: int = 0
    vertical: bool = False
    creator_name: str = ""
    creator_url: str = ""
    # Search provenance and cheap pre-download signals (thumbnail, tags, size).
    query: str = ""
    thumb_url: str = ""
    tags: tuple[str, ...] = ()
    duration: float = 0.0
    width: int = 0
    height: int = 0
    score: float = 0.0
    # Licence proof (owner, 24 Nov): page of the clip and the licence at the time of use.
    page_url: str = ""
    licence: str = ""
    licence_url: str = ""


from .keywords import select_keywords


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Video download must use a safe HTTPS URL")
    host = parsed.hostname.lower()
    permitted = os.getenv("VIDEO_ALLOWED_HOSTS", "coverr.co,*.coverr.co,*.cloudfront.net,videos.pexels.com,images.pexels.com").split(",")
    permitted = [h.lower().strip() for h in permitted if h.strip()]
    if not any(host == h or (h.startswith("*.") and host.endswith(h[1:])) for h in permitted):
        raise ValueError(f"Video URL host is not approved: {host}. Check domain, then extend VIDEO_ALLOWED_HOSTS.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Literal IP addresses are not permitted")
    # Defense in depth against DNS resolving to local/private addresses.
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise ValueError("Unsafe destination IP for video download")


def download_video(url: str, destination: Path, session=None, max_bytes=180_000_000) -> Path:
    session = session or requests.Session()
    destination.parent.mkdir(parents=True, exist_ok=True)
    current = url
    for _ in range(5):
        _check_host(current)
        response = session.get(current, timeout=(15, 90), stream=True, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            from urllib.parse import urljoin
            current = urljoin(current, response.headers["Location"])
            response.close()
            continue
        response.raise_for_status()
        length = int(response.headers.get("Content-Length") or 0)
        if length > max_bytes:
            raise ValueError("Video too large")
        size = 0
        try:
            with destination.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("Video exceeds download limit")
                        f.write(chunk)
        finally:
            response.close()
        if size < 1024:
            raise ValueError("Downloaded video is unexpectedly small")
        return destination
    raise RuntimeError("Too many video redirects")


def coverr_page(item: dict) -> str:
    """Public Coverr page of a clip, when the API gives a plain slug."""
    import re as _re
    slug = str(item.get("slug") or "")
    return f"https://coverr.co/videos/{slug}" if _re.fullmatch(r"[a-z0-9-]{3,120}", slug) else ""


def _coverr_creator_metadata(item: dict) -> tuple[str, str]:
    """Use contributor credit only when explicitly provided by Coverr."""
    creator = item.get("creator") or item.get("contributor") or item.get("author") or item.get("user")
    if not isinstance(creator, dict):
        return "", ""
    name = str(creator.get("name") or creator.get("display_name")
               or creator.get("full_name") or "").strip()
    url = str(creator.get("profile_url") or creator.get("url") or "").strip()
    if not name:
        return "", ""
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in ("coverr.co", "www.coverr.co")
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        return "", ""
    return name[:100], url


# Coverr refusing this API key for the rest of the run (hourly limit 429, or 403 on the
# search / download-stats endpoints). Once seen, further Coverr calls are skipped instead of
# burning more requests, and the quality check before the review mail knows why.
COVERR_BLOCK: dict[str, int | None] = {"status": None}
COVERR_REQUESTS = 0
from .budgets import COVERR_PER_RUN as COVERR_MAX_REQUESTS  # headroom below the hourly allowance


def reserve_coverr_request():
    global COVERR_REQUESTS
    if coverr_blocked():
        raise RuntimeError(f"Coverr {coverr_blocked()}: blocked for this run")
    if COVERR_REQUESTS >= COVERR_MAX_REQUESTS:
        COVERR_BLOCK["status"] = 429
        raise RuntimeError("Coverr 429: local request budget exhausted")
    COVERR_REQUESTS += 1



def coverr_blocked() -> int | None:
    return COVERR_BLOCK["status"]


def describe_error(exc: Exception) -> str:
    """'HTTPError 403' etc.; marks Coverr as blocked on 403/429 from api.coverr.co."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    url = str(getattr(response, "url", "") or getattr(getattr(exc, "request", None), "url", "") or "")
    if status is None and "429" in str(exc) and "Coverr" in str(exc):
        status = 429
    if status in (403, 429) and ("coverr" in url or "Coverr" in str(exc)):
        COVERR_BLOCK["status"] = status
    return f"{type(exc).__name__}{f' {status}' if status else ''}"


def record_coverr_download(video_id: str, api_key: str, *, session=None):
    """Report selected clip to Coverr stats; never transmit signed media URLs."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", video_id):
        raise ValueError("Unsafe Coverr video ID")
    if not api_key:
        raise RuntimeError("Coverr API key missing for download tracking")
    session = session or requests.Session()
    reserve_coverr_request()
    response = session.patch(
        f"https://api.coverr.co/videos/{video_id}/stats/downloads",
        headers={"x-api-key": api_key}, timeout=20)
    if response.status_code in (403, 429):
        COVERR_BLOCK["status"] = response.status_code
    response.raise_for_status()
    if response.status_code != 204:
        raise RuntimeError("Coverr download stats endpoint did not acknowledge selection")


# Coverr matches every word of a query, so long art-direction phrases return 0 hits
# (verified in the live run 44588789496). Each phrase therefore gets a 1–2 word core
# query that keeps its specific subject before the broad lane word is used.
SHORT_QUERIES = {
    "quiet forest sunrise backlight": "forest sunrise", "river flowing natural light": "river",
    "wind moving trees morning": "trees wind", "warm minimal white room wood floor": "minimal interior",
    "ocean window gentle sunlight": "ocean sunlight",
    "vintage drum machine sampler pads hands": "drum machine", "MPC 2000 XL sampler closeup": "sampler",
    "vinyl record turntable grooves": "vinyl", "analog mixing console knobs": "mixing console",
    "cassette tape reel studio": "cassette", "guitar wood grain notebook paper": "guitar",
    "studio musician hands keyboard": "keyboard", "dim recording studio candlelight": "recording studio",
    "California coastal highway sunset": "coastal highway", "palm trees golden hour": "palm trees",
    "vintage roadside motel dusk": "motel", "old American diner after dark": "diner",
    "classic car interior road trip": "road trip", "faded Super 8 summer film": "vintage summer",
    "dusty open highway desert": "desert road", "old Hollywood empty ballroom": "ballroom",
    "90s California skateboard fisheye low angle": "skateboard", "skater asphalt sunset silhouette": "skater sunset",
    "skateboard wheels sidewalk closeup": "skateboard wheels", "skatepark natural light documentary": "skatepark",
    "old camcorder street skate": "street skate",
    "Y2K digital camera flash night": "camera flash", "early 2000s camcorder grain": "camcorder",
    "VHS tracking retro tape": "vhs", "consumer digicam summer": "summer friends",
    "night drive coastal road": "night drive", "purple blue neon city reflection": "neon",
    "lonely motel night lights": "motel night", "city road rain window": "rain window",
}
_FILLER = {"a", "an", "the", "of", "and", "with", "in", "on", "at", "after", "old", "vintage", "classic",
           "faded", "quiet", "warm", "dim", "gentle", "natural", "minimal", "lonely", "early", "dusty",
           "light", "closeup", "low", "angle", "documentary", "grain", "film", "90s", "2000s"}


def short_query(editorial_phrase: str) -> str:
    """1–2 core words for Coverr's all-words search (curated map, then a word filter)."""
    if editorial_phrase in SHORT_QUERIES:
        return SHORT_QUERIES[editorial_phrase]
    words = [w for w in re.findall(r"[a-z0-9]+", editorial_phrase.lower()) if w not in _FILLER]
    return " ".join(words[:2]) or editorial_phrase


def query_ladder(editorial_phrase: str) -> list[str]:
    """Specific → core → broad, without duplicates."""
    ladder = []
    for query in (editorial_phrase, short_query(editorial_phrase), _coverr_search_phrase(editorial_phrase)):
        if query.lower() not in [q.lower() for q in ladder]:
            ladder.append(query)
    return ladder


def _coverr_search_phrase(editorial_phrase: str) -> str:
    """Map a detailed art-direction shot to Coverr's short search vocabulary."""
    term = editorial_phrase.lower()
    if "skate" in term or "bmx" in term:
        return "skateboarding"
    if any(x in term for x in ("mpc", "sampler", "console", "synth", "cassette", "vinyl",
                                "guitar", "notebook", "keyboard", "recording studio",
                                "drum machine", "turntable", "music")):
        return "music"
    if "sunset" in term or "golden hour" in term or "palm" in term:
        return "sunset"
    if any(x in term for x in ("forest", "tree", "river", "water", "wind", "earth")):
        return "nature"
    if any(x in term for x in ("highway", "driving", "road", "car interior", "motel", "diner")):
        return "road"
    if any(x in term for x in ("coast", "malibu", "beach", "ocean", "meditation", "white room", "driftwood")):
        return "beach"
    if any(x in term for x in ("sunset", "palm", "retro", "vintage", "y2k", "super 8", "digicam", "cybershot", "1960", "americana", "hollywood")):
        return "sunset"
    if any(x in term for x in ("urban", "night", "neon", "city", "street", "rooftop")):
        return "city"
    return "nature"


def portrait_only() -> bool:
    """Strict mode: never use landscape clips, even if too few portrait clips exist."""
    return os.getenv("CARLECOOL_PORTRAIT_ONLY", "false").strip().lower() in ("true", "1", "yes")


def allow_landscape() -> bool:
    """Landscape clips may FILL UP when portrait supply is short (default), never lead.

    Coverr's free catalogue is mostly 16:9; a strict portrait rule produced zero clips
    for many art-direction phrases. Set CARLECOOL_PORTRAIT_ONLY=true for strict mode.
    """
    return not portrait_only()


MIN_PORTRAIT_CLIPS = 4


def landscape_equal() -> bool:
    """Owner, 25 Nov: portrait is not required — landscape clips are reframed to 9:16
    (content-aware crop with a slow pan), which looks deliberate. Default on;
    CARLECOOL_PREFER_PORTRAIT=true restores the old portrait-first rule."""
    return os.getenv("CARLECOOL_PREFER_PORTRAIT", "false").strip().lower() not in ("true", "1", "yes", "on")


def _is_portrait(item: dict) -> bool:
    if item.get("is_vertical") is True:
        return True
    try:
        return int(item.get("max_height") or 0) > int(item.get("max_width") or 0) > 0
    except (TypeError, ValueError):
        return False


def _coverr_request(session, key: str, query: str, page_size: int):
    if coverr_blocked():
        raise RuntimeError(f"Coverr {coverr_blocked()}: blocked earlier in this run; request skipped")
    reserve_coverr_request()
    r = session.get(
        "https://api.coverr.co/videos",
        headers={"x-api-key": key},
        params={"query": query, "page_size": page_size, "sort": "popular", "urls": "true"},
        timeout=30,
    )
    if r.status_code in (403, 429):
        COVERR_BLOCK["status"] = r.status_code
        raise RuntimeError(f"Coverr {r.status_code}: request limit reached; try again later")
    r.raise_for_status()
    return r.json().get("hits", [])


def search_coverr(key: str, mood: str, recent: set[str], session=None, wanted=8, *,
                  keywords=None, page_size: int = 40, per_lane_minimum: int = 4,
                  max_lanes: int = 3, exact: dict[str, tuple[str, ...]] | None = None) -> list[Video]:
    """Search Coverr with the real art-direction phrase, portrait clips only.

    Per lane: full phrase, then its 1–2 word core, then the broad lane word — each
    only while the lane still lacks material. At most 9 requests (free limit: 50/hour).
    """
    if not key:
        return []
    session = session or requests.Session()
    landscape_ok = allow_landscape()
    seen = set()
    per_lane = []
    stop = False
    for editorial in (keywords if keywords is not None else select_keywords(mood))[:max_lanes]:
        if stop:
            break
        lane = []
        # Style search terms are already Coverr words: no broad fallback ("motel" must not
        # turn into generic "road" clips).
        ladder = [editorial, *exact[editorial]] if exact and editorial in exact else query_ladder(editorial)
        for attempt, query in enumerate(ladder):
            # Stop descending once this lane has enough on-style material.
            if attempt and (sum(1 for v in lane if v.vertical) >= per_lane_minimum
                            or len(lane) >= 2 * per_lane_minimum):
                break
            try:
                hits = _coverr_request(session, key, query, page_size)
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                # Keep everything found so far (e.g. hourly limit hit on a later lane).
                status = getattr(getattr(exc, "response", None), "status_code", "")
                print(f"Coverr '{query}' failed ({type(exc).__name__} {status}); keeping earlier results")
                stop = True
                break
            print(f"Coverr '{query}': {len(hits)} hits, "
                  f"{sum(1 for h in hits if _is_portrait(h))} portrait")
            for item in hits:
                vid = str(item.get("id", ""))
                if not vid or vid in seen or vid in recent:
                    continue
                if any(item.get(field) is True for field in
                       ("is_premium", "premium", "is_sponsored", "sponsored", "is_watermarked")):
                    continue
                portrait = _is_portrait(item)
                if not portrait and not landscape_ok:
                    continue
                urls = item.get("urls") or {}
                video_url = urls.get("mp4_download") or urls.get("mp4")
                if not video_url:
                    continue
                seen.add(vid)
                creator_name, creator_url = _coverr_creator_metadata(item)
                tags = tuple(str(t).lower() for t in (item.get("tags") or [])
                             if isinstance(t, str))[:30]
                try:
                    duration = float(item.get("duration") or 0)
                except (TypeError, ValueError):
                    duration = 0.0
                lane.append(Video(vid, "coverr", url=video_url, title=item.get("title", ""),
                                  views=int(item.get("views") or 0), vertical=portrait,
                                  creator_name=creator_name, creator_url=creator_url,
                                  query=editorial,
                                  thumb_url=str(item.get("thumbnail") or item.get("poster") or ""),
                                  tags=tags, duration=duration,
                                  width=int(item.get("max_width") or 0),
                                  height=int(item.get("max_height") or 0), page_url=coverr_page(item)))
        per_lane.append(sorted(lane, key=lambda x: (x.vertical, x.views), reverse=True))
    if stop and not any(per_lane):
        raise RuntimeError("Coverr unavailable before any usable result")
    found = []
    while len(found) < wanted and any(per_lane):
        next_lanes = []
        for lane in per_lane:
            if lane and len(found) < wanted:
                found.append(lane.pop(0))
            if lane:
                next_lanes.append(lane)
        per_lane = next_lanes
    return found[:wanted]


def fallback_videos(recent: set[str]) -> list[Video]:
    manifest = json.loads(Path("assets/stock/manifest.json").read_text(encoding="utf-8"))
    videos = []
    for item in manifest.get("clips", []):
        if not item.get("license_confirmed") or not item.get("commercial_social_allowed"):
            continue
        path = Path("assets/stock") / item.get("file", "")
        if not path.resolve().is_relative_to(Path("assets/stock").resolve()):
            raise ValueError("Fallback video escaped stock directory")
        s3_key = item.get("s3_key")
        if (path.is_file() and path.suffix.lower() in (".mp4", ".mov", ".mkv")) or s3_key:
            videos.append(Video(str(item["id"]), "owned", path=str(path) if path.is_file() else None,
                                s3_key=str(s3_key) if s3_key else None, title=str(item.get("title", ""))))
    return sorted(videos, key=lambda v: v.id in recent)


def gather_videos(key: str, mood: str, recent: set[str], wanted=8, *, keywords=None,
                  max_lanes: int = 3, exact: dict[str, tuple[str, ...]] | None = None) -> list[Video]:
    """Pexels portrait clips first (if PEXELS_API_KEY is set), then Coverr, then owned stock."""
    from . import pexels
    phrases = list(keywords if keywords is not None else select_keywords(mood))
    selected: list[Video] = []
    if pexels.configured():
        try:
            selected += pexels.search_pexels(os.getenv("PEXELS_API_KEY", "").strip(), phrases, recent,
                                             wanted=wanted)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"Pexels unavailable; continuing with Coverr: {type(exc).__name__}")
    try:
        if not coverr_blocked():
            selected += search_coverr(key, mood, recent, wanted=wanted, keywords=phrases,
                                  max_lanes=max_lanes, exact=exact)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"Coverr unavailable; using licensed local fallback: {type(exc).__name__}")
    # Keep fallback candidates even if providers return metadata but downloads fail.
    return selected + fallback_videos(recent)


def fetch_owned_stock(video: Video, destination: Path) -> Path:
    """Fetch a licensed fallback stock clip from a private S3/R2 bucket."""
    if video.path:
        return Path(video.path)
    if not video.s3_key or ".." in Path(video.s3_key).parts:
        raise ValueError("Invalid stock S3 key")
    bucket = os.getenv("STOCK_S3_BUCKET", "")
    if not bucket:
        raise ValueError("STOCK_S3_BUCKET is required to retrieve private fallback videos")
    import boto3
    client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, video.s3_key, str(destination))
    return destination
