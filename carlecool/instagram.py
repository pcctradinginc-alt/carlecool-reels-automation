"""Meta Instagram Graph API — Facebook Login for Business / binary Reel upload."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

import requests


class Instagram:
    def __init__(self, user_id: str, token: str, api_version: str = "v24.0", session=None):
        if not user_id.isdecimal() or not token:
            raise ValueError("Set IG_USER_ID (numeric) and IG_ACCESS_TOKEN")
        self.user_id = user_id
        self.token = token
        self.api_version = api_version
        self.base = f"https://graph.facebook.com/{api_version}"
        self.session = session or requests.Session()

    def _request(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.token}"
        r = self.session.request(method, f"{self.base}/{path.lstrip('/')}", headers=headers, timeout=45, **kwargs)
        r.raise_for_status()
        return r.json()

    def create_and_upload(self, video: Path, caption: str) -> str:
        payload = self._request("POST", f"{self.user_id}/media", data={
            "media_type": "REELS", "upload_type": "resumable", "caption": caption,
            "share_to_feed": "true",
        })
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
