"""SoundCloud API (public track metadata only; no unapproved MP3 ripping)."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path

import requests

from .config import Settings


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    permalink_url: str
    genre: str = ""
    tag_list: str = ""
    created_at: str = ""
    duration_ms: int = 0
    downloadable: bool = False
    uploader_id: str = ""
    artwork_url: str = ""

    @classmethod
    def parse(cls, data: dict) -> "Track":
        urn = str(data.get("urn") or data.get("id") or "").strip()
        if not urn or not data.get("title"):
            raise ValueError("Track requires an id/urn and title")
        return cls(
            id=urn.split(":")[-1],
            title=str(data["title"]),
            permalink_url=str(data.get("permalink_url") or ""),
            genre=str(data.get("genre") or ""),
            tag_list=str(data.get("tag_list") or ""),
            created_at=str(data.get("created_at") or ""),
            duration_ms=int(data.get("duration") or data.get("duration_ms") or 0),
            downloadable=bool(data.get("downloadable", False)),
            uploader_id=str((data.get("user") or {}).get("id")
                            or str((data.get("user") or {}).get("urn") or "").split(":")[-1]),
            artwork_url=str(data.get("artwork_url") or ""),
        )


def _get(session, url, *, token, params=None):
    r = session.get(url, params=params, headers={"Authorization": f"OAuth {token}"}, timeout=25)
    r.raise_for_status()
    return r.json()


def fetch_tracks(config: Settings, session=None, pool: dict | None = None) -> list[Track]:
    """Return 20 newest uploaded public tracks sorted by creation date — or, with a
    playlist song pool (songpool.py), the owner's public tracks of that set."""
    fixture = Path("data/tracks.json")
    if not (config.sc_client_id and config.sc_client_secret):
        if not fixture.exists():
            raise RuntimeError("Set SoundCloud API credentials or provide data/tracks.json (metadata only).")
        raw = json.loads(fixture.read_text(encoding="utf-8"))
        return sorted((Track.parse(t) for t in raw), key=lambda t: t.created_at, reverse=True)[:20]
    session = session or requests.Session()
    token_response = session.post(
        "https://secure.soundcloud.com/oauth/token",
        auth=(config.sc_client_id, config.sc_client_secret),
        data={"grant_type": "client_credentials"}, timeout=25,
    )
    token_response.raise_for_status()
    token = token_response.json()["access_token"]
    user = _get(session, "https://api.soundcloud.com/resolve", token=token, params={"url": config.profile_url})
    user_urn = user.get("urn") or (f"soundcloud:users:{user['id']}" if user.get("id") else None)
    if not user_urn:
        raise RuntimeError("Could not resolve SoundCloud profile")
    owner_id = str(user.get("id") or str(user.get("urn") or "").split(":")[-1])
    if not owner_id.isdecimal():
        raise RuntimeError("Resolved SoundCloud artist has no numeric user ID")
    if pool and pool.get("mode") == "playlist":
        return _playlist_tracks(session, token, pool, owner_id)
    raw_tracks = []
    next_url = f"https://api.soundcloud.com/users/{user_urn}/tracks"
    params = {"limit": 50, "linked_partitioning": "true"}
    # Two pages avoids runaway pagination, but gets enough to sort the 20 newest.
    for _ in range(2):
        payload = _get(session, next_url, token=token, params=params)
        items = payload.get("collection", []) if isinstance(payload, dict) else payload
        raw_tracks.extend(items)
        next_url = payload.get("next_href") if isinstance(payload, dict) else None
        if not next_url:
            break
        params = None
    tracks = [Track.parse(t) for t in raw_tracks if t.get("title") and t.get("sharing", "public") == "public"]
    # Prefer the profile explicitly resolved via /resolve, never uploader IDs
    # from untrusted playlist/repost entries.
    if any(t.uploader_id and t.uploader_id != owner_id for t in tracks):
        raise RuntimeError("Track uploader differs from resolved CarleCool profile")
    tracks = [replace(t, uploader_id=owner_id) for t in tracks]
    return sorted(tracks, key=lambda t: t.created_at, reverse=True)[:20]


def _playlist_tracks(session, token: str, pool: dict, owner_id: str) -> list[Track]:
    """Public tracks of one of the owner's sets, in set order; fails closed when empty."""
    playlist = _get(session, "https://api.soundcloud.com/resolve", token=token,
                    params={"url": pool["playlist_url"]})
    if str(playlist.get("kind") or "playlist") not in ("playlist", "system-playlist"):
        raise RuntimeError("Song pool URL is not a SoundCloud set")
    pl_owner = str((playlist.get("user") or {}).get("id")
                   or str((playlist.get("user") or {}).get("urn") or "").split(":")[-1])
    if pl_owner and pl_owner != owner_id:
        raise RuntimeError("Song pool set belongs to another SoundCloud account")
    items = playlist.get("tracks") or []
    if not items or any("title" not in t for t in items):
        urn = playlist.get("urn") or f"soundcloud:playlists:{playlist.get('id')}"
        payload = _get(session, f"https://api.soundcloud.com/playlists/{urn}/tracks", token=token,
                       params={"limit": 100, "linked_partitioning": "true"})
        items = payload.get("collection", []) if isinstance(payload, dict) else payload
    tracks = []
    for t in items:
        if not t.get("title") or t.get("sharing", "public") != "public":
            continue
        track = Track.parse(t)
        if track.uploader_id and track.uploader_id != owner_id:
            continue  # reposts by others in the set are never used
        tracks.append(replace(track, uploader_id=owner_id))
    if not tracks:
        raise RuntimeError(f"Song pool '{pool.get('label') or pool['playlist_url']}' has no public tracks of the owner")
    print(f"Song pool: {len(tracks)} tracks from '{pool.get('label') or pool['playlist_url']}'")
    return tracks
