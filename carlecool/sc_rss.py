"""Inspect artist-authorized public SoundCloud podcast RSS enclosures.

Read-only diagnostic: this module deliberately never fetches enclosure audio.
RSS publishing is an explicit artist-controlled SoundCloud permission.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def inspect_feed(xml_bytes: bytes, track_ids: set[str]) -> dict:
    if len(xml_bytes) > 2_000_000:
        raise ValueError("RSS document exceeds 2 MB")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError("Invalid SoundCloud RSS XML") from exc
    matched = 0
    enclosures = 0
    for item in root.findall(".//item")[:200]:
        guid = item.findtext("guid") or ""
        enclosed = item.find("enclosure")
        if enclosed is None:
            continue
        url = enclosed.get("url", "")
        kind = enclosed.get("type", "")
        if not url.startswith("https://") or not kind.startswith("audio/"):
            continue
        enclosures += 1
        found = re.search(r"tracks[/:-]([0-9]{1,24})", guid)
        if found and found.group(1) in track_ids:
            matched += 1
    return {"rss_audio_entries": enclosures, "newest_20_matched": matched}


def public_rss_url(user_id: str) -> str:
    if not re.fullmatch(r"[0-9]{1,24}", user_id):
        raise ValueError("Unsafe SoundCloud profile ID")
    return f"https://feeds.soundcloud.com/users/soundcloud:users:{user_id}/sounds.rss"



def matching_rss_audio_url(xml_bytes: bytes, track_id: str) -> str:
    """Find one artist-published RSS enclosure for the exact SoundCloud track ID."""
    if len(xml_bytes) > 2_000_000 or not re.fullmatch(r"[0-9]{1,24}", track_id):
        raise ValueError("Unsafe RSS input")
    root = ET.fromstring(xml_bytes)
    matches = []
    for item in root.findall(".//item")[:500]:
        guid = item.findtext("guid") or ""
        matched = re.search(r"tracks[/:-]([0-9]{1,24})", guid)
        if not matched or matched.group(1) != track_id:
            continue
        enclosure = item.find("enclosure")
        if enclosure is None or not (enclosure.get("type", "").startswith("audio/")):
            continue
        url = enclosure.get("url") or ""
        _safe_audio_url(url)
        matches.append(url)
    if len(matches) != 1:
        raise FileNotFoundError("Exactly one publicly authorized SoundCloud RSS audio enclosure is required")
    return matches[0]


def _safe_audio_url(url: str) -> None:
    """Accept only known public SoundCloud feed/media CDN hosts over HTTPS."""
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.username or parts.password
            or parts.port not in (None, 443) or not parts.hostname):
        raise ValueError("RSS audio URL is not a safe HTTPS endpoint")
    host = parts.hostname.lower()
    allow = (
        host == "feeds.soundcloud.com" or
        host == "api.soundcloud.com" or
        host.endswith(".sndcdn.com") or
        host.endswith(".cloudfront.net")
    )
    if not allow:
        raise ValueError("RSS media host is not an approved SoundCloud delivery host")
    for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(result[4][0]).is_global:
            raise ValueError("RSS audio host resolves to a nonpublic address")


def download_owned_rss_audio(track_id: str, owner_id: str, destination, *,
                             session=None, max_bytes=150_000_000):
    """Use explicitly published podcast RSS audio for the owner's own Reel.

    Nothing is committed, uploaded to GitHub, or retained between runner jobs.
    No SoundCloud streams or private audio endpoints are scraped.
    """
    from pathlib import Path
    from urllib.parse import urljoin
    import requests
    import subprocess
    session = session or requests.Session()
    feed = public_rss_url(owner_id)
    _safe_audio_url(feed)
    response = session.get(feed, timeout=(12, 35), allow_redirects=False)
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("SoundCloud RSS exceeds 2 MB")
    url = matching_rss_audio_url(response.content, track_id)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        for _ in range(6):
            _safe_audio_url(url)
            r = session.get(url, stream=True, timeout=(20, 120), allow_redirects=False)
            try:
                if r.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, r.headers["Location"])
                    continue
                r.raise_for_status()
                kind = r.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if kind and not (kind.startswith("audio/") or kind == "application/octet-stream"):
                    raise ValueError("SoundCloud RSS enclosure returned non-audio content")
                count = 0
                with path.open("wb") as out:
                    for piece in r.iter_content(chunk_size=1024*256):
                        if piece:
                            count += len(piece)
                            if count > max_bytes:
                                raise ValueError("RSS audio exceeds approved maximum")
                            out.write(piece)
                if count < 4096:
                    raise ValueError("RSS audio download is unexpectedly short")
                # Reject error pages or video masquerading as podcast audio.
                # imageio-ffmpeg provides FFmpeg but not a separate ffprobe binary.
                # Inspect declared media streams without decoding or transcoding.
                checked = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-i", str(path)],
                    capture_output=True, text=True, timeout=30)
                if not re.search(r"Stream #\\d+:\\d+(?:\\[[^]]+\\])?(?:\\([^)]*\\))?: Audio:",
                                 checked.stderr):
                    raise ValueError("RSS enclosure is not decodable audio")
                return path
            finally:
                r.close()
        raise RuntimeError("SoundCloud RSS audio exceeded safe redirect limit")
    except Exception:
        path.unlink(missing_ok=True)
        raise
