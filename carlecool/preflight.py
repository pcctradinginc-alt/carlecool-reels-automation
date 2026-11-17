"""Read-only integration preflight for public GitHub Actions.

Never publishes, uploads original media, emails anyone, or prints credentials.
Only checks whether each provider can be reached with the configured credentials.
"""
from __future__ import annotations

import imaplib
import os
import smtplib
import ssl
from dataclasses import dataclass
import requests

from carlecool.config import Settings
from carlecool.instagram import Instagram
from carlecool.soundcloud import fetch_tracks
from carlecool.mailstore import _sent_mailbox
from carlecool.sc_rss import inspect_feed, public_rss_url

@dataclass
class Check:
    provider: str
    result: str
    detail: str

def _http_status(exc: BaseException) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = int(exc.response.status_code)
        return f"HTTP {status}"  # Never disclose response bodies or request headers
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return "connection timed out"
    if isinstance(exc, requests.ConnectionError):
        return "network connection failed"
    return type(exc).__name__

def instagram() -> Check:
    if not os.getenv("IG_ACCESS_TOKEN"):
        return Check("Instagram", "BLOCKED", "IG_ACCESS_TOKEN secret missing")
    try:
        client = Instagram(os.getenv("IG_USER_ID", ""), os.environ["IG_ACCESS_TOKEN"],
                           os.getenv("GRAPH_API_VERSION", "v27.0"))
        account = client.verify_access()
        if not account.get("username"):
            return Check("Instagram", "WARN", "assigned Instagram ID found, but username field unavailable")
        return Check("Instagram", "PASS", "Unified Login asset can be read (no publishing)")
    except Exception as exc:
        return Check("Instagram", "FAIL", _http_status(exc))

def soundcloud() -> Check:
    if not os.getenv("SOUNDCLOUD_CLIENT_ID") or not os.getenv("SOUNDCLOUD_CLIENT_SECRET"):
        return Check("SoundCloud", "BLOCKED", "app client ID/secret missing")
    try:
        tracks = fetch_tracks(Settings())
        if not tracks:
            return Check("SoundCloud", "WARN", "API accessible but no eligible public tracks")
        downloadable = sum(bool(track.downloadable) for track in tracks)
        newest = str(tracks[0].id)
        return Check("SoundCloud", "PASS",
                     f"{len(tracks)} public tracks; {downloadable} marked downloadable; "
                     f"newest public track ID: {newest} (metadata only)")
    except Exception as exc:
        return Check("SoundCloud", "FAIL", _http_status(exc))

def coverr() -> Check:
    key = os.getenv("COVERR_API_KEY", "").strip()
    if not key:
        return Check("Coverr", "BLOCKED", "COVERR_API_KEY secret missing")
    try:
        res = requests.get("https://api.coverr.co/videos", headers={"x-api-key": key},
                           params={"query": "skateboarding", "page_size": 5,
                                   "sort": "popular", "urls": "true"},
                           timeout=(10, 25))
        res.raise_for_status()
        data = res.json()
        hits = data.get("hits")
        if not isinstance(hits, list):
            return Check("Coverr", "WARN", "API reachable but unexpected response format")
        downloadable = sum(bool((x.get("urls") or {}).get("mp4_download")
                                or (x.get("urls") or {}).get("mp4")) for x in hits)
        if not downloadable:
            return Check("Coverr", "WARN",
                         f"Search returned {len(hits)} videos but 0 signed MP4 links")
        return Check("Coverr", "PASS",
                     f"Search returned {len(hits)} videos, {downloadable} signed MP4 links")
    except Exception as exc:
        return Check("Coverr", "FAIL", _http_status(exc))

def gmail() -> Check:
    address = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    recipient = os.getenv("REVIEW_EMAIL", "").strip()
    if not all((address, password, recipient)):
        return Check("Gmail", "BLOCKED", "GMAIL_ADDRESS/GMAIL_APP_PASSWORD/REVIEW_EMAIL missing")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30,
                              context=ssl.create_default_context()) as conn:
            conn.login(address, password)
    except Exception as exc:
        return Check("Gmail SMTP", "FAIL", _http_status(exc))
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30) as conn:
            conn.login(address, password)
            _sent_mailbox(conn)
    except Exception as exc:
        return Check("Gmail IMAP", "FAIL", _http_status(exc))
    return Check("Gmail", "PASS", "SMTP login and IMAP Sent-folder access work; no message sent")


def soundcloud_rss() -> Check:
    """Discover only publicly enabled podcast audio; never request enclosure media."""
    client_id = os.getenv("SOUNDCLOUD_CLIENT_ID", "")
    secret = os.getenv("SOUNDCLOUD_CLIENT_SECRET", "")
    if not client_id or not secret:
        return Check("SoundCloud RSS", "WARN", "SoundCloud app credentials missing")
    try:
        oauth = requests.post("https://secure.soundcloud.com/oauth/token",
                              auth=(client_id, secret),
                              data={"grant_type": "client_credentials"},
                              timeout=(10, 25))
        oauth.raise_for_status()
        token = oauth.json()["access_token"]
        profile = requests.get("https://api.soundcloud.com/resolve",
                               headers={"Authorization": f"OAuth {token}"},
                               params={"url": "https://soundcloud.com/carlecool"}, timeout=(10, 25))
        profile.raise_for_status()
        who = profile.json()
        user_id = str(who.get("id") or str(who.get("urn", "")).split(":")[-1])
        url = public_rss_url(user_id)
        response = requests.get(url, timeout=(10, 25), allow_redirects=False)
        if response.status_code in (404, 403):
            return Check("SoundCloud RSS", "WARN", "No accessible official RSS feed")
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            return Check("SoundCloud RSS", "WARN", "RSS XML too large to inspect")
        tracks = fetch_tracks(Settings())
        stats = inspect_feed(response.content, {x.id for x in tracks})
        if stats["newest_20_matched"] == 0:
            return Check("SoundCloud RSS", "WARN",
                         f"RSS audio entries: {stats['rss_audio_entries']}; 0 of newest 20 match")
        return Check("SoundCloud RSS", "PASS",
                     f"RSS contains {stats['newest_20_matched']} of newest 20 tracks with audio enclosures")
    except Exception as exc:
        return Check("SoundCloud RSS", "WARN", _http_status(exc))

def audio_readiness() -> Check:
    if os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD"):
        return Check("Original audio", "WARN", "private Gmail master-audio retrieval configured; actual files unverified")
    if os.getenv("AUDIO_S3_BUCKET") and os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        return Check("Original audio", "WARN", "private S3 configured; actual track files not yet checked")
    if os.getenv("SC_ALLOW_OFFICIAL_DOWNLOADS", "").lower() in ("true", "1", "yes"):
        return Check("Original audio", "WARN", "SoundCloud official-download mode configured; access unverified")
    return Check("Original audio", "BLOCKED", "no verified private audio source configured")

def publication_gates() -> Check:
    if os.getenv("PUBLISH_ENABLED", "").strip().lower() in ("true", "1", "yes"):
        return Check("Publishing", "WARN", "PUBLISH_ENABLED is ON; human issue approval still required")
    return Check("Publishing", "PASS", "disabled; no live posts possible from preflight")

def main() -> None:
    results = [instagram(), soundcloud(), soundcloud_rss(), coverr(), gmail(),
               audio_readiness(), publication_gates()]
    lines = ["## CarleCool — read-only provider preflight", "",
             "No posting, media uploading, or email sending performed.", "",
             "| Integration | Status | Reason |",
             "|---|---|---|"]
    for item in results:
        lines.append(f"| {item.provider} | {item.result} | {item.detail} |")
    report = "\n".join(lines) + "\n"
    print(report)   # Only sanitized status; no token, email address or raw API error
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(report)
    failing = [x.provider for x in results if x.result in {"FAIL", "BLOCKED"}]
    if failing:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
