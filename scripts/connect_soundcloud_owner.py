#!/usr/bin/env python3
"""ONE-TIME local SoundCloud OAuth PKCE bootstrap (runs on your Mac).

Requires cloned repo, GitHub CLI (gh auth login), and already registered redirect URI.
No credentials or authorization codes are printed to GitHub Actions or stored as plaintext.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import sys
import webbrowser

from cryptography.fernet import Fernet
from carlecool.sc_owner import (
    new_pkce, authorize_url, validate_callback, exchange_code,
    read_owner_identity, persist_encrypted_token_state, TOKEN_FILE,
)

REPO = "pcctradinginc-alt/carlecool-reels-automation"


def main():
    client_id = os.getenv("SOUNDCLOUD_CLIENT_ID", "").strip()
    secret = os.getenv("SOUNDCLOUD_CLIENT_SECRET", "").strip()
    redirect = os.getenv("SOUNDCLOUD_REDIRECT_URI", "").strip()
    if not all((client_id, secret, redirect)):
        raise SystemExit("Set SOUNDCLOUD_CLIENT_ID, SOUNDCLOUD_CLIENT_SECRET and SOUNDCLOUD_REDIRECT_URI locally first.")
    if not redirect.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
        raise SystemExit("Use only a registered HTTPS or localhost callback.")
    verifier, challenge = new_pkce()
    state = secrets.token_urlsafe(32)
    url = authorize_url(client_id, redirect, challenge, state)
    print("Opening SoundCloud authorization in your browser. Log into your CarleCool account.")
    print("If the browser cannot open automatically, visit:", url)
    webbrowser.open(url)
    print("After approval, copy the COMPLETE redirected URL from the browser address bar.")
    print("If localhost shows a connection error, the callback URL is still visible in the address bar.")
    callback = input("Full redirect URL (never paste into ChatGPT): ").strip()
    code = validate_callback(callback, redirect, state)
    tokens = exchange_code(client_id, secret, redirect, code, verifier)
    owner = read_owner_identity(tokens["access_token"],
                                os.getenv("SOUNDCLOUD_PROFILE_URL", "https://soundcloud.com/carlecool"))
    print("SoundCloud CarleCool owner confirmed. No tracks were downloaded.")
    print("The tokens will be encrypted; only the random decryption key goes to GitHub Secrets.")
    choice = input("Store encrypted token and enable secure GitHub Actions rotation? [yes/NO] ")
    if choice != "yes":
        raise SystemExit("No credentials written to GitHub.")
    root = Path(__file__).resolve().parents[1]
    path = root / TOKEN_FILE
    key = Fernet.generate_key()
    # Set secret first. gh reads secret on stdin, not a process argument.
    subprocess.run(["gh", "secret", "set", "SC_OWNER_FERNET_KEY",
                    "--repo", REPO], input=key + b"\n", check=True)
    persist_encrypted_token_state(path, tokens, key.decode("ascii"))
    relative = str(TOKEN_FILE)
    subprocess.run(["git", "-C", str(root), "add", relative], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m",
                    "auth: initialize encrypted SoundCloud owner session"], check=True)
    subprocess.run(["git", "-C", str(root), "push", "origin", "HEAD:main"], check=True)
    subprocess.run(["gh", "variable", "set", "SC_OWNER_OAUTH_ENABLED",
                    "--repo", REPO, "--body", "true"], check=True)
    print("Encrypted owner session activated; daily read-only owner-check enabled.")
    print("No track audio access or Instagram posting enabled.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Avoid traceback with sensitive responses/URLs.
        print("SoundCloud OAuth setup failed:", type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
