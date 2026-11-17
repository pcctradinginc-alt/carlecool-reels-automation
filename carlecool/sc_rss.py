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
