"""Preview-only CLI. Publication requires separate owner-approved Gmail workflow."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from .analysis import analyze_audio
from .aesthetic import editorial_brief
from .audio import locate_original
from .config import Settings
from .keywords import select_keywords
from .render import render_reel
from .soundcloud import fetch_tracks
from .state import load_state, pick_track
from .video import download_video, gather_videos, fetch_owned_stock, record_coverr_download


def caption_for(track, videos) -> str:
    caption = f"🎧 {track.title}\n"
    if track.permalink_url:
        caption += f"🎶 Full track: {track.permalink_url}\n"
    if any(v.source == "coverr" for v in videos):
        caption += "🎬 Footage: https://coverr.co\n"
        creators = dict.fromkeys((v.creator_name, v.creator_url) for v in videos
                                 if v.source == "coverr" and v.creator_name and v.creator_url)
        for name, url in creators:
            caption += f"Video by {name} on Coverr: {url}\n"
    return caption + "\n#CarleCool #ElectronicMusic #NewMusic #Reels"


def process(publish: bool) -> None:
    if publish:
        raise RuntimeError("Direct publication is disabled; use the human-approved Gmail workflow")
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
            if video.source == "coverr":
                record_coverr_download(video.id, config.coverr_key)
            selected.append(video)
            paths.append(path)
            if len(paths) >= 8:
                break
        except Exception as exc:
            print(f"Clip unavailable (skipped): {video.id}: {type(exc).__name__}")
    if not paths:
        raise RuntimeError("No licensed clips available; add assets/stock and manifest.json as fallback")
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
    print("Preview mode: no Instagram API call, no state change")


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
