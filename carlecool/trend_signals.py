"""Free, read-only trend signals from Google's public Trending Now RSS.

Google SEARCH interest is NOT proof of a viral Instagram/TikTok video trend.
Fail closed: on 429/network/parse/irrelevance the user's visual style wins.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET

import requests

RSS = "https://trends.google.com/trending/rss?geo=US"
# Exact themed keyword matches only; broad celebrity/current-affairs news ignored.
CUES = {
    "vintage": "vintage roadside motel dusk",
    "retro": "faded Super 8 summer film",
    "nostalgia": "faded Super 8 summer film",
    "analog": "analog mixing console knobs",
    "vinyl": "vinyl record turntable grooves",
    "skateboard": "90s California skateboard fisheye low angle",
    "california": "California coastal highway sunset",
    "sunset": "palm trees golden hour",
    "meditation": "river flowing natural light",
    "wellness": "quiet forest sunrise backlight",
    "lofi": "vinyl record turntable grooves",
    "ambient music": "ocean window gentle sunlight",
}


def parse_feed(content: bytes, *, now: datetime | None = None) -> list[str]:
    """Return fresh, relevant aesthetics only; never return arbitrary trending news."""
    if len(content) > 350_000:
        raise ValueError("Unexpectedly large trend feed")
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(content)
    found = []
    for item in root.findall(".//item")[:100]:
        title = (item.findtext("title") or "").strip().lower()
        raw_date = item.findtext("pubDate") or ""
        try:
            date = parsedate_to_datetime(raw_date).astimezone(timezone.utc)
        except (ValueError, TypeError, IndexError):
            continue
        if not now - timedelta(days=7) <= date <= now + timedelta(minutes=5):
            continue
        for word in CUES:
            if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", title):
                if word not in found:
                    found.append(word)
    return found[:5]


def fetch_signals(*, session=None) -> dict:
    session = session or requests.Session()
    try:
        response = session.get(RSS, allow_redirects=False, timeout=(5, 12),
                               headers={"User-Agent": "CarleCoolPublicTrendResearch/1.0"})
        if response.status_code != 200:
            return {"source": "Google Trending Now RSS", "status": "unavailable", "topics": []}
        if len(response.content) > 350_000:
            raise ValueError("oversized RSS")
        topics = parse_feed(response.content)
        return {"source": "Google Trending Now RSS", "status": "ok",
                "topics": topics, "interpretation": "search_interest_not_video_virality"}
    except (requests.RequestException, ET.ParseError, ValueError):
        return {"source": "Google Trending Now RSS", "status": "unavailable", "topics": []}


def apply_trend(keywords: list[str], signals: dict) -> list[str]:
    """Use at most one safe trend as the third query, preserving Coverr API quota."""
    if len(keywords) < 3 or signals.get("status") != "ok":
        return keywords
    matching = [CUES[t] for t in signals.get("topics", []) if t in CUES]
    if not matching:
        return keywords
    return [*keywords[:2], matching[0]]
