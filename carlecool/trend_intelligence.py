"""Viral Intelligence Engine — trend scout, NOT a third Creative Director (owner, 28 Nov).

"CarleCool folgt nicht den Trends. CarleCool interpretiert Trends in seiner eigenen
Bildsprache." This module reads the versioned trend memory (data/trend_registry.json:
creative MECHANISMS with source, evidence, momentum and expiry) and the free Google
Trending-Now RSS (search interest only — never treated as proof of video virality), and
reports which mechanisms are alive and how fresh they are. No scraping, no paid service,
no invented trends: an entry is "verified" only when the owner confirmed it.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

PATH = Path("data/trend_registry.json")
CATEGORIES = ("emotion", "storytelling", "aesthetic", "editing", "hook", "culture", "sound")


def load(path: Path = PATH) -> list[dict]:
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("trends") or [])
    except (OSError, ValueError):
        return []


def _day(text: str | None) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


def active(trends: list[dict], today: date | None = None) -> list[dict]:
    today = today or datetime.now(timezone.utc).date()
    return [t for t in trends if (_day(t.get("expires")) or today) >= today and t.get("category") in CATEGORIES]


def freshness(trend: dict, today: date | None = None) -> float:
    """1.0 when just noted, falling linearly to 0 at the expiry date."""
    today = today or datetime.now(timezone.utc).date()
    noted = _day((trend.get("evidence") or {}).get("noted")) or today
    expires = _day(trend.get("expires")) or today
    span = max(1, (expires - noted).days)
    return round(max(0.0, min(1.0, 1 - (today - noted).days / span)), 3)


def momentum(trend: dict, google_topics: list[str] | None = None) -> float:
    """Registry momentum, nudged up when Google search interest touches the trend's words
    (search interest is a weak cultural signal, not video virality)."""
    m = float(trend.get("momentum") or 0.0)
    if google_topics and any(k in google_topics for k in trend.get("keywords") or []):
        m += 0.1
    return round(min(1.0, m), 3)


def evidence_quality(trend: dict) -> str:
    ev = trend.get("evidence") or {}
    return "verified" if ev.get("verified") else "unverified"
