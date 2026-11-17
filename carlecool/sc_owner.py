"""SoundCloud OAuth 2.1 owner session, *read-only metadata probe*.

Never downloads, records, caches or persists any audio from SoundCloud.
Tokens are encrypted at rest using a key stored exclusively in GitHub Secrets.
SoundCloud refresh tokens are single-use: each refresh must be committed before
the access token is used, or the workflow fails closed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from urllib.parse import urlencode, urlsplit, parse_qs

from cryptography.fernet import Fernet, InvalidToken
import requests

TOKEN_FILE = Path("data/soundcloud-owner.enc")
AUTH_HOST = "https://secure.soundcloud.com"
API_HOST = "https://api.soundcloud.com"


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    if not all((client_id, redirect_uri, challenge, state)):
        raise ValueError("Missing OAuth 2.1 authorization input")
    return AUTH_HOST + "/authorize?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": state,
    })


def validate_callback(callback: str, redirect_uri: str, state: str) -> str:
    parsed = urlsplit(callback.strip())
    expected = urlsplit(redirect_uri)
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        expected.scheme, expected.netloc, expected.path
    ):
        raise ValueError("OAuth callback does not match registered redirect URI")
    qs = parse_qs(parsed.query)
    if qs.get("state") != [state]:
        raise ValueError("OAuth callback state mismatch")
    if "error" in qs:
        raise ValueError("SoundCloud declined OAuth authorization")
    codes = qs.get("code", [])
    if len(codes) != 1 or not codes[0]:
        raise ValueError("OAuth callback lacks exactly one authorization code")
    return codes[0]


def _token_request(payload: dict, session=None) -> dict:
    session = session or requests
    response = session.post(
        AUTH_HOST + "/oauth/token",
        data=payload,
        headers={"Accept": "application/json"},
        timeout=(15, 40),
    )
    response.raise_for_status()
    item = response.json()
    if not isinstance(item, dict) or not item.get("access_token") or not item.get("refresh_token"):
        raise RuntimeError("SoundCloud did not return both owner OAuth tokens")
    duration = int(item.get("expires_in", 3600))
    if duration < 60:
        raise RuntimeError("Unexpected SoundCloud OAuth token lifetime")
    return {
        "access_token": item["access_token"],
        "refresh_token": item["refresh_token"],
        "expires_at": int(time.time()) + duration,
    }


def exchange_code(client_id: str, client_secret: str, redirect_uri: str,
                  code: str, verifier: str, session=None) -> dict:
    return _token_request({
        "grant_type": "authorization_code",
        "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "code": code, "code_verifier": verifier,
    }, session=session)


def refresh_tokens(client_id: str, client_secret: str,
                   refresh_token: str, session=None) -> dict:
    return _token_request({
        "grant_type": "refresh_token", "client_id": client_id,
        "client_secret": client_secret, "refresh_token": refresh_token,
    }, session=session)


def encrypt_tokens(tokens: dict, key: str) -> bytes:
    return Fernet(key.encode("ascii")).encrypt(json.dumps(tokens).encode("utf-8"))


def decrypt_tokens(encrypted: bytes, key: str) -> dict:
    try:
        tokens = json.loads(Fernet(key.encode("ascii")).decrypt(encrypted))
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Owner token could not be decrypted; reconnect SoundCloud") from exc
    if not all(tokens.get(k) for k in ("access_token", "refresh_token", "expires_at")):
        raise RuntimeError("Incomplete encrypted owner OAuth state")
    return tokens


def _id(item: dict) -> str:
    return str(item.get("id") or str(item.get("urn", "")).split(":")[-1])


def read_owner_identity(token: str, profile_url: str, session=None) -> dict:
    """Verify that this OAuth grant represents the configured artist profile."""
    session = session or requests
    headers = {"Authorization": "OAuth " + token, "Accept": "application/json"}
    me = session.get(API_HOST + "/me", headers=headers, timeout=25)
    me.raise_for_status()
    profile = session.get(API_HOST + "/resolve", headers=headers,
                          params={"url": profile_url}, timeout=25)
    profile.raise_for_status()
    if _id(me.json()) != _id(profile.json()) or not _id(me.json()).isdigit():
        raise RuntimeError("Connected SoundCloud user is not the CarleCool profile")
    return {"id": _id(me.json()), "connected": True}


def probe_owned_tracks(token: str, owner_id: str, track_ids: list[str], session=None) -> dict:
    """Inspect ownership and download metadata; do not fetch any audio bytes."""
    session = session or requests
    headers = {"Authorization": "OAuth " + token, "Accept": "application/json"}
    results = {"checked": 0, "owned": 0, "downloadable": 0, "download_url_available": 0}
    for track_id in track_ids[:5]:
        if not re.fullmatch(r"[0-9]{1,24}", track_id):
            raise ValueError("Unsafe SoundCloud track ID")
        response = session.get(API_HOST + "/tracks/soundcloud:tracks:" + track_id,
                               headers=headers, timeout=25)
        response.raise_for_status()
        item = response.json()
        results["checked"] += 1
        uploader = item.get("user") or {}
        if _id(uploader) != owner_id:
            raise RuntimeError("SoundCloud track is not owned by the authenticated artist")
        results["owned"] += 1
        results["downloadable"] += int(item.get("downloadable") is True)
        link = str(item.get("download_url") or "")
        if link.startswith(API_HOST + "/tracks/") and link.endswith("/download"):
            results["download_url_available"] += 1
    return results


def persist_encrypted_token_state(path: Path, state: dict, key: str):
    """Atomic write, no plaintext file, no token logging."""
    encrypted = encrypt_tokens(state, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def commit_rotated_token_state(path: Path):
    """Only GitHub Actions on main may persist one-use refresh-token rotation."""
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("Cannot persist refresh token outside main GitHub Actions")
    subprocess.run(["git", "config", "user.name", "CarleCool Auth Bot"], check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", str(path)], check=True)
    subprocess.run(["git", "commit", "-m", "auth: rotate encrypted SoundCloud owner token"], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)


def owner_session(*, token_file: Path = TOKEN_FILE, commit_rotation=True,
                  session=None, now=None) -> str:
    """Return short-lived access token; securely rotate and commit if expired."""
    key = os.getenv("SC_OWNER_FERNET_KEY", "")
    client_id = os.getenv("SOUNDCLOUD_CLIENT_ID", "")
    secret = os.getenv("SOUNDCLOUD_CLIENT_SECRET", "")
    if not key or not client_id or not secret or not token_file.is_file():
        raise RuntimeError("Owner OAuth not yet configured: see docs/soundcloud-owner-oauth.md")
    state = decrypt_tokens(token_file.read_bytes(), key)
    now = int(time.time()) if now is None else int(now)
    if int(state["expires_at"]) > now + 180:
        return state["access_token"]
    # Single-use rotation; commit new encrypted refresh token before making further API calls.
    rotated = refresh_tokens(client_id, secret, state["refresh_token"], session=session)
    persist_encrypted_token_state(token_file, rotated, key)
    if commit_rotation:
        commit_rotated_token_state(token_file)
    return rotated["access_token"]


def main():
    """Manual GitHub Actions probe; no downloads, uploads or user-content edits."""
    from .soundcloud import fetch_tracks
    from .config import Settings
    token = owner_session()
    identity = read_owner_identity(token, os.getenv("SOUNDCLOUD_PROFILE_URL",
                                                   "https://soundcloud.com/carlecool"))
    tracks = fetch_tracks(Settings())
    result = probe_owned_tracks(token, identity["id"], [x.id for x in tracks[:5]])
    msg = (f"Owner OAuth PASS; latest tracks checked: {result['checked']}; "
           f"owned: {result['owned']}; public downloads enabled: {result['downloadable']}; "
           f"official download_url exposed: {result['download_url_available']}. "
           "No audio was downloaded or published.")
    print(msg)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("## SoundCloud owner OAuth probe\n\n" + msg + "\n")


if __name__ == "__main__":
    main()
