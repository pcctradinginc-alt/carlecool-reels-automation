"""CLI for daily previews and gated, idempotent live publishing."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from .analysis import analyze_audio
from .aesthetic import editorial_brief
from .audio import locate_original
from .config import Settings
from .instagram import Instagram
from .keywords import select_keywords
from .render import render_reel
from .soundcloud import fetch_tracks
from .state import commit_state, load_state, pick_track, save_state
from .video import download_video, gather_videos, fetch_owned_stock


def caption_for(track, videos) -> str:
    caption = f"🎧 {track.title}\n"
    if track.permalink_url:
        caption += f"🎶 Full track: {track.permalink_url}\n"
    if any(v.source == "coverr" for v in videos):
        caption += "🎬 Footage via Coverr · https://coverr.co (clip credits in production log)\n"
    return caption + "\n#CarleCool #ElectronicMusic #NewMusic #Reels"


def process(publish: bool) -> None:
    config = Settings()
    config.validate()
    state = load_state()
    tracks = fetch_tracks(config)
    if not tracks:
        raise RuntimeError("No public SoundCloud tracks found")
    track = pick_track(tracks, state, config.cooldown_days)
    print(f"Selected track: {track.title} (SoundCloud ID {track.id})")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    audio = locate_original(track, output_dir / "original.mp3")
    features = analyze_audio(str(audio), config.reel_seconds, track.genre)
    print(f"Estimated musical features: BPM={features.bpm}, mood={features.mood}, energy={features.energy}")
    recent = {video_id for record in state.get("published", [])[-20:] for video_id in record.get("video_ids", [])}
    keywords = select_keywords(features.mood, features.energy, features.bpm, seed=track.id)
    print(f"Video search phrases: {keywords}")
    candidates = gather_videos(config.coverr_key, features.mood, recent, wanted=9, keywords=keywords)
    selected = []
    paths = []
    for video in candidates:
        try:
            path = fetch_owned_stock(video, output_dir / f"stock_{len(paths):02d}.mp4") if video.source == "owned" else download_video(video.url, output_dir / f"stock_{len(paths):02d}.mp4")
            selected.append(video)
            paths.append(path)
            if len(paths) >= 8:
                break
        except Exception as exc:
            print(f"Clip unavailable (skipped): {video.id}: {type(exc).__name__}: {exc}")
    if not paths:
        raise RuntimeError("No licensed clips available; add assets/stock and manifest.json as fallback")
    if publish:
        raise RuntimeError("Direct publishing is disabled: use the human-approved email workflow")
        if not config.publish_enabled:
            raise RuntimeError("Live publishing disabled. Set PUBLISH_ENABLED=true as a GitHub secret.")
        if len(set(v.id for v in selected)) < 5:
            raise RuntimeError("Need >=5 distinct cleared clips to publish; quality gate failed")
        if any(v.source == "coverr" for v in selected) and not config.coverr_permission_confirmed:
            raise RuntimeError("Coverr attribution/usage terms are not approved for this Instagram workflow")
        if not (config.ig_user_id and config.ig_access_token):
            raise RuntimeError("IG_USER_ID / IG_ACCESS_TOKEN are missing")
    out = output_dir / f"carlecool_{track.id}.mp4"
    details = render_reel(audio, paths, features, out, config.reel_seconds)
    metadata = {
        "track_id": track.id, "title": track.title, "permalink": track.permalink_url,
        "features": vars(features), "video_ids": [v.id for v in selected],
        "footage_sources": [{"id": v.id, "provider": v.source, "title": v.title} for v in selected],
        "caption": caption_for(track, selected), "search_keywords": keywords,
        "visual_direction": editorial_brief(features.mood, features.energy, features.bpm),
        "output": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), **details,
    }
    (output_dir / "reel_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rendered preview: {out} ({details['scenes']} beat-aligned scenes)")
    if not publish:
        print("Preview mode: no Instagram API call, no state change")
        return

    # Reserve the operation *and push* BEFORE calling the external posting API.
    # If a subsequent Meta call/connection fails ambiguously, future runs will STOP.
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Live publishing must run in GitHub Actions for durable journal protection")
    timestamp = datetime.now(timezone.utc).isoformat()
    state["pending"] = {"track_id": track.id, "at": timestamp, "sha256": metadata["sha256"]}
    save_state(state)
    commit_state(f"journal: reserve Reel for {track.id}")

    ig = Instagram(config.ig_user_id, config.ig_access_token, config.graph_version)
    # Do not retry creation blindly; duplicate remote uploads could be ambiguous.
    container_id = ig.create_and_upload(out, caption_for(track, selected))
    state["pending"]["container_id"] = container_id
    save_state(state)
    commit_state(f"journal: Instagram container {container_id}")
    media_id = ig.finish(container_id)
    state["published"].append({
        "track_id": track.id, "at": timestamp, "video_ids": [v.id for v in selected],
        "instagram_media_id": media_id, "instagram_container_id": container_id,
        "sha256": metadata["sha256"],
    })
    state["pending"] = None
    save_state(state)
    commit_state(f"journal: Reel published {media_id}")
    print(f"Published Instagram Reel media id: {media_id}")


def main():
    parser = argparse.ArgumentParser(description="CarleCool video pipeline")
    parser.add_argument("--mode", choices=["preview", "publish"], default="preview")
    args = parser.parse_args()
    process(publish=args.mode == "publish")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PIPELINE FAILED (fail closed): {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
