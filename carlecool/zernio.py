"""Zernio's official REST API adapter for consented CarleCool video publishing.

No publishing is possible without the separate, explicit GitHub owner approval.
Upload uses Zernio's temporary signed file endpoint; no public GitHub media.
See https://docs.zernio.com/guides/media-uploads and /platforms/tiktok.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid

import requests

API = "https://zernio.com/api"


def _check_media_url(url: str, *, upload: bool) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError("Unsafe Zernio media endpoint")
    if upload:
        if not host.endswith(".r2.cloudflarestorage.com") or host == ".r2.cloudflarestorage.com":
            raise ValueError("Unexpected Zernio signed upload host")
        if not parsed.query or not parsed.path.endswith(".mp4"):
            raise ValueError("Unexpected signed video upload URL")
    else:
        if host != "media.zernio.com" or parsed.query or not parsed.path.startswith("/temp/") or not parsed.path.endswith(".mp4"):
            raise ValueError("Unexpected Zernio media URL")
    return url


class Zernio:
    def __init__(self, api_key: str, *, session=None):
        if not api_key or len(api_key) < 12:
            raise ValueError("ZERNIO_API_KEY is not configured")
        self.key = api_key
        self.session = session or requests.Session()

    def _post(self, path: str, data: dict, *, idempotency_key: str | None = None) -> dict:
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self.session.post(API + path, json=data, headers=headers,
                                     timeout=(15, 75), allow_redirects=False)
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Unexpected Zernio API redirect")
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected Zernio API response")
        return result

    def verify_connections(self, accounts: dict[str, str]) -> dict[str, bool]:
        """Read-only account-ID check; never posts media or reveals account data."""
        result = self.session.get(
            API + "/v1/accounts", headers={"Authorization": "Bearer " + self.key},
            timeout=(10, 30),
        )
        result.raise_for_status()
        body = result.json()
        rows = body.get("accounts") or []
        if not isinstance(rows, list):
            raise RuntimeError("Zernio account list is invalid")
        verified = {}
        for platform, account_id in accounts.items():
            matches = [r for r in rows if str(r.get("id") or r.get("_id") or "") == account_id
                       and r.get("platform") == platform]
            if len(matches) != 1:
                raise RuntimeError("Requested Zernio " + platform + " account is not connected")
            if matches[0].get("isActive") is False or matches[0].get("enabled") is False:
                raise RuntimeError("Zernio " + platform + " account is disabled")
            verified[platform] = True
        return verified

    def preflight_tiktok(self, account_id: str) -> None:
        """Read-only final validation of actual TikTok posting eligibility."""
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json"}
        health = self.session.get(API + "/v1/accounts/health",
                                  headers=headers, timeout=(10, 30),
                                  allow_redirects=False)
        health.raise_for_status()
        if health.status_code != 200:
            raise RuntimeError("Unexpected Zernio account-health response")
        status = health.json()
        accounts = status.get("accounts") or []
        matching = [a for a in accounts
                    if str(a.get("accountId", "")) == account_id
                    and a.get("platform") == "tiktok"]
        if len(matching) != 1:
            raise RuntimeError("TikTok account missing from account health")
        account = matching[0]
        if (not account.get("canPost") or not account.get("tokenValid")
                or account.get("needsReconnect")):
            raise RuntimeError("TikTok token or posting permissions are not ready")
        info = self.session.get(
            API + "/v1/accounts/" + account_id + "/tiktok/creator-info",
            params={"mediaType": "video"},
            headers=headers, timeout=(10, 30), allow_redirects=False)
        info.raise_for_status()
        if info.status_code != 200:
            raise RuntimeError("Unexpected TikTok creator-info response")
        payload = info.json()
        levels = payload.get("privacyLevels") or []
        permitted = {entry.get("value") if isinstance(entry, dict) else entry
                     for entry in levels}
        if "PUBLIC_TO_EVERYONE" not in permitted:
            raise RuntimeError("TikTok creator does not currently permit public direct posts")
        if payload.get("creator", {}).get("canPostMore") is False:
            raise RuntimeError("TikTok daily posting allowance has been reached")
        options = (payload.get("postingLimits") or {}).get("interactionSettings") or {}
        for setting, selected in (("allow_comment", True),
                                  ("allow_duet", False),
                                  ("allow_stitch", False)):
            entry = options.get(setting) or {}
            if selected and entry.get("enabled") is False:
                raise RuntimeError("TikTok creator disables a required interaction: " + setting)

    def upload(self, video: Path) -> str:
        """Upload a reviewed MP4 via a time-limited signed URL."""
        video = Path(video)
        if video.suffix.lower() != ".mp4" or not video.is_file():
            raise ValueError("Original MP4 is missing")
        size = video.stat().st_size
        if not 1024 <= size <= 16_000_000:
            raise ValueError("Original MP4 size is unsafe")
        result = self._post("/v1/media/presign", {
            "filename": "carlecool-approved.mp4",
            "contentType": "video/mp4",
            "size": size,
        })
        upload_url = _check_media_url(result.get("uploadUrl", ""), upload=True)
        public_url = _check_media_url(result.get("publicUrl", ""), upload=False)
        with video.open("rb") as stream:
            response = self.session.put(upload_url, data=stream,
                                        headers={"Content-Type": "video/mp4"},
                                        timeout=(15, 120), allow_redirects=False)
            response.raise_for_status()
            if response.status_code not in (200, 201, 204):
                raise RuntimeError("Unexpected Zernio media upload redirect")
        return public_url

    def publish(self, *, media_url: str, caption: str, target: str,
                instagram_id: str, tiktok_id: str,
                ai_generated: bool, sha256: str, issue_number: int,
                audio_name: str = "") -> dict:
        media_url = _check_media_url(media_url, upload=False)
        requested = {
            "instagram": ["instagram"], "tiktok": ["tiktok"],
            "both": ["instagram", "tiktok"],
        }.get(target)
        if requested is None:
            raise ValueError("Invalid platform selection")
        ids = {"instagram": instagram_id, "tiktok": tiktok_id}
        if any(not ids[name] for name in requested):
            raise RuntimeError("A requested Zernio account ID is missing")
        platforms = [{"platform": name, "accountId": ids[name]} for name in requested]
        body = {
            "content": caption,
            "mediaItems": [{"url": media_url, "type": "video"}],
            "platforms": platforms,
            "publishNow": True,
        }
        if "tiktok" in requested:
            body["tiktokSettings"] = {
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "allow_comment": True,
                "allow_duet": False,
                "allow_stitch": False,
                "content_preview_confirmed": True,
                "express_consent_given": True,
                "video_made_with_ai": bool(ai_generated),
            }
        for platform in platforms:
            if platform["platform"] != "instagram":
                continue
            data = {}
            if ai_generated:
                data["isAiGenerated"] = True
            if audio_name:
                # Zernio: "Renames the Reel's own audio (replaces 'Original Audio')".
                # TikTok has no equivalent API field; its sound keeps the account name.
                data["audioName"] = audio_name
            if data:
                platform["platformSpecificData"] = data
        # Stable across retries for the same approved bytes and target.
        identity = f"carlecool|{issue_number}|{sha256}|{target}"
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        return self._post("/v1/posts", body, idempotency_key=key)


IN_FLIGHT = {"pending", "processing", "uploading"}
TERMINAL = {"published", "failed", "cancelled"}
POST_ID = re.compile(r"[A-Za-z0-9_-]{6,64}")


def _get_post(client: "Zernio", post_id: str) -> dict:
    """Read-only status of one post (GET /v1/posts/{postId})."""
    if not POST_ID.fullmatch(post_id or ""):
        raise ValueError("Invalid Zernio post id")
    response = client.session.get(f"{API}/v1/posts/{post_id}",
                                  headers={"Authorization": "Bearer " + client.key,
                                           "Accept": "application/json"},
                                  timeout=(15, 45), allow_redirects=False)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Zernio post response")
    # Normalise to the create-post shape {"post": {...}}.
    return data if isinstance(data.get("post"), dict) else {"post": data}


def wait_for_result(client: "Zernio", response: dict, target: str, *,
                    timeout: float = 720, interval: float = 15,
                    sleep=None, clock=None) -> tuple[dict, bool]:
    """Poll until every requested platform is published/failed/cancelled.

    Zernio answers publishNow with transient entry statuses (`uploading` …) while the
    video is still being processed; TikTok typically finishes minutes later.
    Returns (latest response, finished). Network errors during polling are tolerated
    until the deadline: the post already exists, so we only ever READ here.
    """
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    post_id = str((response.get("post") or {}).get("_id") or "")
    latest = response
    deadline = clock() + timeout
    while True:
        entries = published_platforms(latest, target)
        if all(e.get("status") in TERMINAL for e in entries.values()):
            return latest, True
        if not post_id or clock() >= deadline:
            return latest, False
        sleep(interval)
        try:
            latest = _get_post(client, post_id)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print("Zernio status check failed, retrying:", type(exc).__name__)


def published_platforms(response: dict, target: str) -> dict[str, dict]:
    """Report every platform separately; 207 partial is NEVER treated as success."""
    post = response.get("post") or {}
    expected = {"instagram": {"instagram"}, "tiktok": {"tiktok"},
                "both": {"instagram", "tiktok"}}[target]
    records = post.get("platforms") or []
    if not isinstance(records, list):
        raise RuntimeError("Zernio publication status is missing")
    seen = {}
    for entry in records:
        name = entry.get("platform")
        if name in expected and name not in seen:
            seen[name] = entry
    if set(seen) != expected:
        raise RuntimeError("Zernio did not return a status for each requested platform")
    return seen
