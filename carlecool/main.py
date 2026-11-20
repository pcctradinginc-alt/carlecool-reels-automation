"""Preview-only CLI. Publication requires separate owner-approved Gmail workflow."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

from .analysis import analyze_audio
from .aesthetic import editorial_brief
from .creative import load_profile, choose_shots, validate_profile
from .audio import locate_original
from .video import Video
from .naming import song_label
from .config import Settings
from .keywords import select_keywords
from .render import render_reel
from .soundcloud import fetch_tracks
from .state import load_state
from .history import load_preview_history, pick_preview_track, recent_video_ids
from .video import download_video, gather_videos, fetch_owned_stock, record_coverr_download


def caption_for(track, videos) -> str:
    caption = f"🎧 {song_label(track.title)}\n"
    if any(v.source == "ai" for v in videos):
        caption += "✨ Enthält KI-generierte Filmszenen (LTX-2.3)\n"
    if any(v.source == "coverr" for v in videos):
        caption += "🎬 Footage by Coverr: https://coverr.co\n"
        creators = dict.fromkeys((v.creator_name, v.creator_url) for v in videos
                                 if v.source == "coverr" and v.creator_name and v.creator_url)
        for name, url in creators:
            caption += f"Video by {name} on Coverr: {url}\n"
    if any(v.source == "pexels" for v in videos):
        caption += "🎬 Videos provided by Pexels: https://www.pexels.com\n"
        names = dict.fromkeys(v.creator_name for v in videos if v.source == "pexels" and v.creator_name)
        for name in names:
            caption += f"Video by {name} on Pexels\n"
    return caption.rstrip() + "\n\n#carlecool #instrumental #electronic #rap #producer"


def fill_up(reserve, accept, full) -> None:
    """Accept landscape fill-in clips one by one; a failing clip is skipped, never fatal.

    (Run 44607728662 crashed because Coverr's download-stats call returned 403 for a
    single fill-in clip; the portrait path already skipped such clips.)
    """
    for video, path in reserve:
        if full():
            break
        try:
            accept(video, path)
        except Exception as exc:
            print(f"Clip unavailable (skipped): {video.id}: {type(exc).__name__}")


def process(publish: bool, *, track_id: str | None = None, creative_profile: dict | None = None) -> None:
    if publish:
        raise RuntimeError("Direct publication is disabled; use the human-approved Gmail workflow")
    config = Settings()
    config.validate()
    state = load_state()
    previews = load_preview_history()
    tracks = fetch_tracks(config)
    if not tracks:
        raise RuntimeError("No public SoundCloud tracks found")
    profile = validate_profile(creative_profile) if creative_profile is not None else load_profile()
    from .creative_v5 import enabled as creative_v5_enabled
    v5 = creative_v5_enabled()
    # Never run the experimental director on daily schedules or review revisions.
    if (v5 and os.getenv("GITHUB_ACTIONS") == "true"
            and os.getenv("GITHUB_WORKFLOW") != "CarleCool — Creative v5 FREE private preview"):
        raise RuntimeError("Creative v5 is restricted to its isolated, no-publish workflow")
    v5_plan = None
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    destination = output_dir / "original.mp3"
    if track_id is not None:
        track = next((t for t in tracks if t.id == str(track_id)), None)
        if track is None:
            raise ValueError('Revision track no longer appears in latest 20 SoundCloud uploads')
        audio = locate_original(track, destination)
    else:
        # Keep balanced random rotation, but skip tracks lacking artist-authorized
        # original audio; no SoundCloud stream ripping or unlicensed substitute.
        remaining = list(tracks[:20])
        while remaining:
            track = pick_preview_track(remaining, previews)
            try:
                destination.unlink(missing_ok=True)
                audio = locate_original(track, destination)
                break
            except FileNotFoundError:
                destination.unlink(missing_ok=True)
                print(f"Skipping SoundCloud ID {track.id}: no authorized original audio available")
                remaining = [candidate for candidate in remaining if candidate.id != track.id]
        else:
            raise FileNotFoundError(
                "No artist-authorized original audio among the newest 20 tracks; "
                "check SoundCloud owner RSS publication or send a private Gmail master")
    print(f"Selected track: {track.title} (SoundCloud ID {track.id})")
    fixed_start = 0.0 if profile["music"] == "beginning" else None
    features = analyze_audio(str(audio), config.reel_seconds, track.genre, fixed_start=fixed_start)
    reel_length = float(features.reel_length or config.reel_seconds)
    print(f"Estimated musical features: BPM={features.bpm}, mood={features.mood}, "
          f"energy={features.energy}, analyzer={features.analyzer}, length={reel_length:.2f}s, "
          f"hook at {features.hook_at:.2f}s")
    recent = recent_video_ids(previews)
    recent.update(video_id for record in state.get("published", [])[-6:]
                  for video_id in record.get("video_ids", []))
    # Unique GitHub run identity changes the art direction on every new email.
    # Local/manual runs also get a fresh seed, while tests can pass a fixed seed.
    import secrets
    edition = os.getenv("GITHUB_RUN_ID") or secrets.token_hex(8)
    profile_queries = choose_shots(profile, track_id=track.id, mood=features.mood,
                                   energy=features.energy, limit=3, run_key=edition)
    # The album cover comes FIRST: it decides what we search for, how candidates
    # are ranked before download and how every clip is colour graded.
    cover = None
    cover_choice = {"method": "disabled", "queries": [], "lanes": []}
    if os.getenv("CARLECOOL_COVER_MATCH", "true").lower() in ("true", "1", "yes"):
        from .cover_visual import fetch_cover
        candidate_cover = output_dir / "public_cover"
        if fetch_cover(getattr(track, "artwork_url", ""), candidate_cover):
            cover = candidate_cover
            from .curation import cover_queries
            cover_choice = cover_queries(cover, profile["weights"], run_key=edition)
    if v5:
        if cover is None:
            raise RuntimeError("Creative v5 requires a readable official SoundCloud cover; no preview sent")
        from .creative_v5 import analyze_cover, search_phrases
        v5_plan = analyze_cover(cover)
        keywords = search_phrases(v5_plan)
        print(f"Creative v5 local cover director: {v5_plan['style']} ({v5_plan['basis']})")
    elif cover_choice.get("queries"):
        from .curation import merge_queries
        keywords = merge_queries(cover_choice, profile_queries)
        print(f"Cover-led search ({cover_choice['method']}): {cover_choice['queries']}")
    else:
        keywords = profile_queries
    trend_signals = {"status": "disabled", "topics": []}
    if not v5 and os.getenv("CARLECOOL_TRENDS", "false").lower() in ("true", "1", "on"):
        from .trend_signals import fetch_signals, apply_trend
        trend_signals = fetch_signals()
        keywords = apply_trend(keywords, trend_signals)
    print(f"Video search phrases: {keywords}")
    candidates = gather_videos(config.coverr_key, features.mood, recent, wanted=24, keywords=keywords)
    from .curation import rank_candidates
    candidates, prerank = rank_candidates(candidates, cover, output_dir / "thumbs",
                                          keep=18 if v5 else 10)
    if v5:
        from .creative_v5 import prioritize_candidates
        candidates = prioritize_candidates(candidates)
    if prerank:
        print(f"Pre-download ranking kept {len(prerank)} of the candidate clips")
    from .render import is_portrait
    from .video import MIN_PORTRAIT_CLIPS, allow_landscape
    selected = []
    paths = []
    stock_limit = 7
    landscape_reserve = []  # downloaded landscape clips, used only to fill up

    def accept(video, path):
        if video.source == "coverr":
            record_coverr_download(video.id, config.coverr_key)
        selected.append(video)
        paths.append(path)

    for video in candidates:
        if len(paths) >= stock_limit:
            break
        try:
            target = output_dir / f"stock_{len(paths) + len(landscape_reserve):02d}.mp4"
            path = fetch_owned_stock(video, target) if video.source == "owned" else download_video(video.url, target)
            if is_portrait(path):
                accept(video, path)
            elif v5 and allow_landscape():
                from .creative_v5 import is_role_candidate
                if is_role_candidate(video):
                    # The two required subjects get priority even when the free
                    # catalog only offers landscape; safe 9:16 smart-crop remains.
                    accept(video, path)
                else:
                    landscape_reserve.append((video, path))
            elif allow_landscape():
                landscape_reserve.append((video, path))
            else:
                print(f"Clip skipped (not portrait): {video.id}")
                if video.source != "owned":
                    path.unlink(missing_ok=True)
        except Exception as exc:
            print(f"Clip unavailable (skipped): {video.id}: {type(exc).__name__}")
    portrait_paths = {p for p in paths if is_portrait(p)}
    portrait_count = len(portrait_paths)
    # Landscape only fills up a thin portrait supply, and always after the portrait clips.
    if portrait_count < MIN_PORTRAIT_CLIPS:
        # Fill up to the normal clip count so a landscape-only catalogue still gives variety.
        fill_up(landscape_reserve, accept, lambda: len(paths) >= stock_limit)
    for video, path in landscape_reserve:
        if path not in paths and video.source != "owned":
            path.unlink(missing_ok=True)
    print(f"Footage: {portrait_count} portrait + {len(paths) - portrait_count} landscape fill-in clips")
    if not paths:
        raise RuntimeError("No licensed clips available; add assets/stock and manifest.json as fallback")
    # Optional AI shot: appended LAST and excluded from the opening/closing shot,
    # because it is short (2 s) and low resolution (512×768).
    if not v5 and profile["ai_video"] and os.getenv("CARLECOOL_AI_VIDEO", "off") == "one":
        try:
            from .ai_video import generate_one
            ai_path = generate_one(keywords[0], output_dir / "ai_experiment.mp4")
            selected.append(Video(id="hf-ltx23-" + track.id, source="ai",
                                  title="LTX 2.3 original AI footage", path=str(ai_path)))
            paths.append(ai_path)
            print("Experimental AI footage ready: 1 scene; no audio uploaded to HF.")
        except Exception as exc:
            # Only emit internally sanitized AIUnavailable status, never raw
            # Gradio HTTP exceptions, signed URLs or optional HF token.
            from .ai_video import AIUnavailable
            reason = str(exc) if isinstance(exc, AIUnavailable) else type(exc).__name__
            print("Experimental AI footage unavailable, Coverr fallback: " + reason)
    cover_matching = {"available": cover is not None, "scores": [],
                      "search": cover_choice, "prerank": prerank}
    if cover is not None:
        # Real-frame re-ranking of downloaded clips decides the opening/closing shot.
        from .cover_visual import rank_by_cover
        order, scores = rank_by_cover(cover, paths)
        if scores and len(order) == len(paths):
            paths = [paths[i] for i in order]
            selected = [selected[i] for i in order]
            cover_matching["scores"] = [scores[i] for i in order]
            print("Album-cover palette matching applied to licensed clips")
        if os.getenv("CARLECOOL_SEMANTIC", "off").lower() == "on":
            from .semantic import score_semantic
            semantic = score_semantic(cover, paths, style=profile["preset"])
            if semantic and len(semantic["order"]) == len(paths):
                order = semantic["order"]
                paths = [paths[i] for i in order]
                selected = [selected[i] for i in order]
                cover_matching["semantic"] = {
                    "model": semantic["model"], "scores": semantic["scores"],
                    "themes": semantic["themes"]}
                print("OpenCLIP semantic cover/frame matching applied")
    v5_signatures = None
    if v5:
        from .creative_v5 import verify_signatures
        v5_signatures = verify_signatures(paths, selected)
        print("Creative v5 signatures verified in separate real clips: woman + skater")
    # Neither the AI shot nor a centre-cropped landscape clip may open or close the Reel.
    no_bookend = {i for i, v in enumerate(selected) if v.source == "ai"}
    if v5_signatures is not None:
        # A cover-world shot, not either mandatory role, anchors the loop.
        no_bookend.update(v5_signatures[role]["index"] for role in ("woman", "skater"))
    no_bookend |= {i for i, path in enumerate(paths) if path not in portrait_paths and selected[i].source != "ai"}
    from . import masterstore
    from .naming import artist_name
    from .titlecard import enabled as title_card_enabled
    title_card = (artist_name(), track.title) if title_card_enabled() else None
    out = output_dir / f"carlecool_{track.id}.mp4"
    try:
        details = render_reel(audio, paths, features, out, reel_length,
                              pace=profile["pace"], analog=profile["analog"], cover=cover,
                              no_bookend=no_bookend, fit_email=not masterstore.configured(),
                              featured_sources=(v5_signatures["woman"]["index"],
                                                v5_signatures["skater"]["index"])
                              if v5_signatures is not None else None,
                              title_card=title_card)
    finally:
        if cover is not None:
            cover.unlink(missing_ok=True)
    metadata = {
        "track_id": track.id, "title": track.title, "permalink": track.permalink_url,
        "song_label": song_label(track.title),
        "features": vars(features), "video_ids": [v.id for v in selected],
        "footage_sources": [{"id": v.id, "provider": v.source, "title": v.title} for v in selected],
        "caption": caption_for(track, selected), "search_keywords": keywords,
        "visual_direction": editorial_brief(features.mood, features.energy, features.bpm),
        "creative_profile": profile,
        "cover_matching": cover_matching,
        "music_analysis": {"analyzer": features.analyzer, "reel_length": reel_length,
                           "hook_at": features.hook_at, "beats": len(features.beats),
                           "downbeats": len(features.downbeats)},
        "trend_signals": trend_signals,
        "output": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), **details,
    }
    if v5:
        metadata["creative_v5"] = {
            "mode": "manual_dry_run_only", "cover_director": v5_plan,
            "signatures": v5_signatures,
            "method": "local OpenCLIP on sampled frames; human visual review required",
            "cost": "existing free stock quotas and local model; no paid provider",
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
