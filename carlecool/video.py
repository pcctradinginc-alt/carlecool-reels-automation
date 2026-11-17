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


from .keywords import select_keywords


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Video download must use a safe HTTPS URL")
    host = parsed.hostname.lower()
    permitted = os.getenv("VIDEO_ALLOWED_HOSTS", "coverr.co,*.coverr.co,*.cloudfront.net").split(",")
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


def record_coverr_download(video_id: str, api_key: str, *, session=None):
    """Report selected clip to Coverr stats; never transmit signed media URLs."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", video_id):
        raise ValueError("Unsafe Coverr video ID")
    if not api_key:
        raise RuntimeError("Coverr API key missing for download tracking")
    session = session or requests.Session()
    response = session.patch(
        f"https://api.coverr.co/videos/{video_id}/stats/downloads",
        headers={"x-api-key": api_key}, timeout=20)
    response.raise_for_status()
    if response.status_code != 204:
        raise RuntimeError("Coverr download stats endpoint did not acknowledge selection")


def _coverr_search_phrase(editorial_phrase: str) -> str:
    """Map a detailed art-direction shot to Coverr's short search vocabulary."""
    term = editorial_phrase.lower()
    if "skate" in term or "bmx" in term:
        return "skateboarding"
    if any(x in term for x in ("coast", "malibu", "beach", "ocean", "meditation", "white room", "driftwood")):
        return "beach"
    if any(x in term for x in ("sunset", "palm", "retro", "vintage", "y2k", "super 8", "digicam", "cybershot", "1960")):
        return "sunset"
    if any(x in term for x in ("urban", "night", "neon", "city", "street", "rooftop")):
        return "city"
    return "nature"


def search_coverr(key: str, mood: str, recent: set[str], session=None, wanted=8, *, keywords=None) -> list[Video]:
    """A maximum of 3 searches (<50/hr free limit); results ranked for vertical fit."""
    if not key:
        return []
    session = session or requests.Session()
    seen = set()
    per_lane = []
    for editorial in (keywords if keywords is not None else select_keywords(mood))[:3]:
        query = _coverr_search_phrase(editorial)
        r = session.get(
            "https://api.coverr.co/videos",
            headers={"x-api-key": key},
            params={"query": query, "page_size": 16, "sort": "popular", "urls": "true"},
            timeout=30,
        )
        if r.status_code == 429:
            raise RuntimeError("Coverr 429: rate limit hit; try cached licensed assets or later schedule")
        r.raise_for_status()
        lane = []
        for item in r.json().get("hits", []):
            vid = str(item.get("id", ""))
            if not vid or vid in seen or vid in recent:
                continue
            if any(item.get(field) is True for field in
                   ("is_premium", "premium", "is_sponsored", "sponsored", "is_watermarked")):
                continue
            seen.add(vid)
            video_url = (item.get("urls") or {}).get("mp4_download") or (item.get("urls") or {}).get("mp4")
            if not video_url:
                continue
            creator_name, creator_url = _coverr_creator_metadata(item)
            lane.append(Video(vid, "coverr", url=video_url, title=item.get("title", ""),
                              views=int(item.get("views") or 0),
                              vertical=bool(item.get("is_vertical")),
                              creator_name=creator_name, creator_url=creator_url))
        per_lane.append(sorted(lane, key=lambda x: (x.vertical, x.views), reverse=True))
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


def gather_videos(key: str, mood: str, recent: set[str], wanted=8, *, keywords=None) -> list[Video]:
    try:
        selected = search_coverr(key, mood, recent, wanted=wanted, keywords=keywords)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"Coverr unavailable; using licensed local fallback: {type(exc).__name__}")
        selected = []
    # Keep fallback candidates even if Coverr returns enough metadata but signed downloads fail.
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
