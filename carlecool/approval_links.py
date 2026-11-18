"""Signed, short-lived links for optional one-click Gmail review confirmations.

A GET is harmless. The hosted Cloudflare Worker must require a second POST,
validate the MAC and atomically consume the draft before posting its GitHub
owner approval. No secret or signed link is ever logged.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import os
import re
from urllib.parse import urlsplit


CHOICES = ("instagram", "tiktok", "both", "discard")
MAX_TTL = 48 * 60 * 60
ISSUE_URL = re.compile(
    r"https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/([1-9][0-9]*)\Z"
)


def approval_links(issue_url: str, metadata: dict, run_id: int,
                   *, base_url: str | None = None, secret: str | None = None,
                   now: int | None = None) -> dict[str, str]:
    """All-or-none: absent configuration keeps GitHub review, never fake URLs."""
    base_url = (base_url if base_url is not None else
                os.getenv("APPROVAL_BASE_URL", "")).strip().rstrip("/")
    secret = secret if secret is not None else os.getenv("APPROVAL_LINK_SECRET", "")
    if not base_url and not secret:
        return {}
    if not base_url or not secret:
        raise RuntimeError("Direct review links need both APPROVAL_BASE_URL and APPROVAL_LINK_SECRET")
    parsed = urlsplit(base_url)
    # Cloudflare's workers.dev endpoint may have a custom HTTPS domain.
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or len(base_url) > 200):
        raise ValueError("Invalid HTTPS approval worker origin")
    if len(secret) < 32:
        raise RuntimeError("APPROVAL_LINK_SECRET needs at least 32 random characters")
    match = ISSUE_URL.fullmatch(issue_url)
    if not match:
        raise ValueError("Approval links require a valid GitHub review issue")
    sha = str(metadata.get("sha256", ""))
    if not re.fullmatch(r"[a-f0-9]{64}", sha) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("Missing immutable reviewed MP4 identity")
    expiry = (int(datetime.now(timezone.utc).timestamp()) if now is None else now) + MAX_TTL
    prefix = f"review/{int(match.group(1))}/{run_id}/{sha}"
    links = {}
    for choice in CHOICES:
        payload = f"{prefix}/{choice}/{expiry}"
        digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"),
                          hashlib.sha256).hexdigest()
        links[choice] = f"{base_url}/{payload}/{digest}"
    return links
