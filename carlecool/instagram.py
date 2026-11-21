"""Meta Graph API with Unified Login (system user access token).

Read-only identity lookup via assigned Instagram assets. No Facebook Page required.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


class Instagram:
    def __init__(self, user_id: str, token: str, api_version: str = "v27.0", session=None):
        user_id = (user_id or "").strip()
        if user_id and not user_id.isdecimal():
            raise ValueError("IG_USER_ID must be numeric or omitted for discovery")
        if not token:
            raise ValueError("Set IG_ACCESS_TOKEN to a Unified Login system user token")
        self.user_id = user_id
        self.token = token
        self.api_version = api_version
        self.base = f"https://graph.facebook.com/{api_version}"
        self.session = session or requests.Session()
        self.verified_account = None

    def _request(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.token}"
        r = self.session.request(method, f"{self.base}/{path.lstrip('/')}", headers=headers, timeout=45, **kwargs)
        r.raise_for_status()
        return r.json()

    def verify_access(self) -> dict:
        """Read-only account discovery; reject missing/ambiguous asset assignments."""
        response = self._request("GET", "me/assigned_instagram_accounts",
                                 params={"fields": "id,username", "limit": 100})
        accounts = response.get("data")
        if not isinstance(accounts, list):
            raise RuntimeError("Unified Login token returned no Instagram account list")
        accounts = [a for a in accounts
                    if isinstance(a, dict) and str(a.get("id", "")).isdecimal()]
        if response.get("paging", {}).get("next"):
            raise RuntimeError("Account list is paginated; supply IG_USER_ID and review assignment")
        if self.user_id:
            matches = [a for a in accounts if str(a["id"]) == self.user_id]
            if len(matches) != 1:
                raise RuntimeError("IG_USER_ID is not assigned to this Unified Login token")
        else:
            if len(accounts) != 1:
                raise RuntimeError(
                    f"Expected one Instagram account, got {len(accounts)}; set IG_USER_ID explicitly")
            matches = accounts
        self.verified_account = {"id": str(matches[0]["id"]),
                                 "username": str(matches[0].get("username", ""))}
        self.user_id = self.verified_account["id"]
        return self.verified_account

    def create_and_upload(self, video: Path, caption: str, *, audio_name: str = "",
                          thumb_offset_ms: int | None = None) -> str:
        if self.verified_account is None:
            self.verify_access()
        data = {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
                "share_to_feed": "true"}
        if audio_name:
            # Replaces "Original audio" with e.g. "carl e cool - nastro azzuro" (set once, at creation).
            data["audio_name"] = audio_name
        if isinstance(thumb_offset_ms, int) and thumb_offset_ms >= 0:
            # Reel cover = end card with the song artwork (shown in the profile grid).
            data["thumb_offset"] = str(thumb_offset_ms)
        payload = self._request("POST", f"{self.user_id}/media", data=data)
        container_id = str(payload["id"])
        upload_url = payload.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{self.api_version}/{container_id}"
        parsed = urlparse(upload_url)
        if parsed.scheme != "https" or parsed.hostname != "rupload.facebook.com":
            raise ValueError("Meta returned an unexpected upload host")
        size = video.stat().st_size
        with video.open("rb") as f:
            r = self.session.post(upload_url, data=f, headers={
                "Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size),
                "Content-Type": "application/octet-stream",
            }, timeout=(30, 300))
        r.raise_for_status()
        upload_response = r.json()
        if upload_response.get("success") is not True:
            raise RuntimeError("Meta did not confirm Reel binary upload")
        return container_id

    def status(self, container_id: str) -> str:
        return str(self._request("GET", str(container_id), params={"fields": "status_code"}).get("status_code", ""))

    def finish(self, container_id: str, *, tries=30, interval=10) -> str:
        if self.verified_account is None:
            raise RuntimeError("Verify assigned Instagram account before publishing")
        for attempt in range(tries):
            status = self.status(container_id)
            if status == "FINISHED":
                result = self._request("POST", f"{self.user_id}/media_publish", data={"creation_id": container_id})
                return str(result["id"])
            if status in {"ERROR", "EXPIRED", "PUBLISHED"}:
                raise RuntimeError(f"Meta container status requires manual reconciliation: {status}")
            if attempt + 1 < tries:
                time.sleep(interval)
        raise RuntimeError("Timed out waiting for Instagram media processing; no blind publish retry")



def main():
    """Read-only connection check. Never uploads or publishes anything."""
    client = Instagram(os.getenv("IG_USER_ID", ""),
                       os.getenv("IG_ACCESS_TOKEN", ""),
                       os.getenv("GRAPH_API_VERSION", "v27.0"))
    account = client.verify_access()
    report = f"Unified Login OK: @{account['username']} (IG_USER_ID: {account['id']}); no Reel published."
    print(report)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f"### Instagram connected\n\n{report}\n")


if __name__ == "__main__":
    main()
