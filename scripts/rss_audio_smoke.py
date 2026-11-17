"""Read one original artist-authorized public RSS enclosure, inspect, delete.

Never saves audio to GitHub, sends mail, contacts Instagram, or publishes.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from carlecool.config import Settings
from carlecool.soundcloud import fetch_tracks
from carlecool.sc_rss import download_owned_rss_audio
from carlecool.analysis import analyze_audio


def main():
    tracks = fetch_tracks(Settings())
    if not tracks:
        raise RuntimeError("No CarleCool public songs found")
    newest = tracks[0]
    if not newest.uploader_id:
        raise RuntimeError("SoundCloud profile identity was not available")
    with tempfile.TemporaryDirectory(prefix="carlecool-rss-") as temp:
        downloaded = download_owned_rss_audio(
            newest.id, newest.uploader_id, Path(temp) / "soundtrack.mp3")
        if downloaded.stat().st_size < 4096:
            raise RuntimeError("No usable audio was retrieved from published RSS")
        features = analyze_audio(str(downloaded), 30, newest.genre)
        if features.seconds < 30:
            raise RuntimeError("RSS audio is too short for CarleCool 30-second Reel")
        print(f"PASS: Author-published RSS audio reachable, decodable, "
              f"duration {features.seconds:.1f}s, BPM estimated; "
              "deleted after check. No Instagram or email calls.")


if __name__ == "__main__":
    main()
