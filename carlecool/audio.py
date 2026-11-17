"""Load the artist's owned original audio, never scrape/record SoundCloud streams."""
from __future__ import annotations

import os
from pathlib import Path
import re
import requests

from .soundcloud import Track


def locate_original(track: Track, destination: Path) -> Path:
    """Try local files, or privately download an exact-match master from S3/R2."""
    directory = Path("assets/audio")
    candidates = [directory / f"{track.id}{extension}" for extension in (".mp3", ".wav", ".flac", ".m4a")]
    local = next((p for p in candidates if p.is_file()), None)
    if local:
        return local
    bucket = os.getenv("AUDIO_S3_BUCKET", "").strip()
    if not bucket and os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD"):
        # Owner-controlled Gmail master inbox is free and private; never scrape
        # SoundCloud streams or use GitHub artifacts for copyrighted music.
        from .mailstore import fetch_owned_audio_from_sent
        try:
            return fetch_owned_audio_from_sent(track.id, destination)
        except FileNotFoundError:
            pass
    if not bucket and os.getenv("SC_ALLOW_OFFICIAL_DOWNLOADS", "").lower() in ("true", "1", "yes") and track.downloadable:
        # Only use the official download-enabled resource on the public track we own.
        client_id = os.getenv("SOUNDCLOUD_CLIENT_ID", "")
        client_secret = os.getenv("SOUNDCLOUD_CLIENT_SECRET", "")
        if client_id and client_secret and re.fullmatch(r"\d+", track.id):
            token_req = requests.post("https://secure.soundcloud.com/oauth/token",
                                      auth=(client_id, client_secret),
                                      data={"grant_type": "client_credentials"}, timeout=25)
            token_req.raise_for_status()
            token = token_req.json()["access_token"]
            download = requests.get(f"https://api.soundcloud.com/tracks/{track.id}/download",
                                    headers={"Authorization": f"OAuth {token}"},
                                    timeout=(20, 120), stream=True)
            download.raise_for_status()
            destination.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            with destination.open("wb") as f:
                for chunk in download.iter_content(1024 * 512):
                    total += len(chunk)
                    if total > 200_000_000:
                        raise ValueError("SoundCloud downloadable track exceeds 200 MB limit")
                    f.write(chunk)
            if total < 4096:
                raise ValueError("SoundCloud download too small")
            return destination
    if not bucket:
        raise FileNotFoundError(
            f"Missing original audio for {track.title!r} (track ID {track.id}). "
            f"Send an email FROM your configured Gmail account TO itself, subject CARLECOOL_AUDIO_{track.id}, attach a file named {track.id}.mp3 (or .wav/.flac/.m4a); or use a private S3/R2 bucket."
        )
    import boto3
    prefix = os.getenv("AUDIO_S3_PREFIX", "carlecool/audio/").strip("/")
    client = boto3.client("s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Only a numeric SoundCloud ID can influence the remote object path.
    if not re.fullmatch(r"\d+", track.id):
        raise ValueError("SoundCloud track id is not numeric")
    key = f"{prefix}/{track.id}.mp3"
    client.download_file(bucket, key, str(destination))
    return destination
