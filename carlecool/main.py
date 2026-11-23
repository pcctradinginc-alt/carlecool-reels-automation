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

MEMORY_REELS = 30  # clips shown in the last 30 preview mails are avoided (fresh ones first)
PRELINGER_CLIPS = 2  # public-domain home movies per Reel (4 made the edit a collage)


def caption_for(track, videos, copy: dict | None = None) -> str:
    """Song line (+ search line / question / niche hashtags from captions.py when `copy`
    is given), then every licence credit."""
    from . import captions
    caption = captions.head(song_label(track.title), copy) if copy else f"🎧 {song_label(track.title)}\n"
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
    if any(v.source == "nasa" for v in videos):
        caption += "🎬 Archive footage: NASA (images.nasa.gov)\n"
    wiki = list(dict.fromkeys(v.creator_name for v in videos if v.source == "wikimedia" and v.creator_name))
    if wiki:
        caption += "🎬 " + "; ".join(wiki) + "\n"
    if any(v.source == "prelinger" for v in videos):
        caption += "🎬 Archive footage: Prelinger Archives, public domain (archive.org)\n"
    tags = captions.tail(copy) if copy else "#carlecool #instrumental #electronic #rap #producer"
    return caption.rstrip() + "\n\n" + tags


class QualityTooLow(RuntimeError):
    """Not enough distinct footage: no review mail rather than a thin, repetitive Reel."""


def check_quality(paths, planned_shots: int, signature_slots: dict) -> None:
    """Minimum before rendering: distinct clips for ~75 % of the shots (each repeated clip
    is visible in a 30 s Reel). Reel #37 had 7 clips for 13 shots after Coverr stopped
    answering. CARLECOOL_MIN_QUALITY=off disables the check."""
    if os.getenv("CARLECOOL_MIN_QUALITY", "on").strip().lower() in ("off", "false", "0", "no"):
        return
    import math
    from .video import coverr_blocked
    distinct = len({str(p) for p in paths})
    needed = max(6, math.ceil(0.75 * planned_shots))
    if distinct >= needed:
        return
    reason = (f"Coverr refused requests (HTTP {coverr_blocked()}, hourly limit) — try again in about an hour"
              if coverr_blocked() else "too few suitable clips after the style filter")
    raise QualityTooLow(f"Quality minimum not met: {distinct} distinct clips for {planned_shots} shots "
                        f"(need {needed}); signature shots: {len(signature_slots)}. {reason}. "
                        "No review mail sent.")


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
            from .video import describe_error
            print(f"Clip unavailable (skipped): {video.id}: {describe_error(exc)}")


def pick_song(tracks, wanted: str) -> str | None:
    """Manual run for one song (workflow input `song`): SoundCloud track id or part of the title."""
    wanted = (wanted or "").strip().lower()
    if not wanted:
        return None
    hit = next((t for t in tracks if t.id == wanted), None) or \
        next((t for t in tracks if wanted in (t.title or "").lower()), None)
    if hit is None:
        raise ValueError(f"Song '{wanted}' not found in the song pool")
    print(f"Song chosen manually: {hit.title}")
    return hit.id


def process(publish: bool, *, track_id: str | None = None, creative_profile: dict | None = None) -> None:
    from .video import COVERR_BLOCK
    COVERR_BLOCK["status"] = None  # fresh for every Reel (also for revisions in one process)
    if publish:
        raise RuntimeError("Direct publication is disabled; use the human-approved Gmail workflow")
    config = Settings()
    config.validate()
    state = load_state()
    previews = load_preview_history()
    from . import songpool
    pool = songpool.load()
    tracks = fetch_tracks(config, pool=pool)
    if not tracks:
        raise RuntimeError("No public SoundCloud tracks found")
    profile = validate_profile(creative_profile) if creative_profile is not None else load_profile()
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    destination = output_dir / "original.mp3"
    if track_id is None:
        track_id = pick_song(tracks, os.getenv("CARLECOOL_SONG", ""))
    if track_id is not None:
        track = next((t for t in tracks if t.id == str(track_id)), None)
        if track is None and pool.get("mode") != "all":
            # Revision of a Reel made before the song pool was limited: look in the newest uploads.
            track = next((t for t in fetch_tracks(config) if t.id == str(track_id)), None)
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
    # Unique GitHub run identity changes the art direction on every new email.
    # Local/manual runs also get a fresh seed, while tests can pass a fixed seed.
    import secrets
    edition = os.getenv("GITHUB_RUN_ID") or secrets.token_hex(8)
    # Length test (≈12 s vs ≈30 s, per song in turn) and what the numbers taught so far.
    from . import performance
    perf_model = performance.load_model()
    length_choice = performance.choose_length(track.id, previews, config.reel_seconds, edition, perf_model)
    print(f"Reel length: {length_choice['bucket']} (target {length_choice['target']:.0f}s; {length_choice['reason']})")
    features = analyze_audio(str(audio), length_choice["target"], track.genre, fixed_start=fixed_start)
    reel_length = float(features.reel_length or length_choice["target"])
    print(f"Estimated musical features: BPM={features.bpm}, mood={features.mood}, "
          f"energy={features.energy}, analyzer={features.analyzer}, length={reel_length:.2f}s, "
          f"hook at {features.hook_at:.2f}s")
    recent = recent_video_ids(previews)
    recent.update(video_id for record in state.get("published", [])[-6:]
                  for video_id in record.get("video_ids", []))
    # The album cover comes FIRST: it picks the style package, what we search for,
    # how candidates are ranked before download and how every clip is graded.
    cover = None
    if os.getenv("CARLECOOL_COVER_MATCH", "true").lower() in ("true", "1", "yes"):
        from .cover_visual import fetch_cover
        candidate_cover = output_dir / "public_cover"
        if fetch_cover(getattr(track, "artwork_url", ""), candidate_cover):
            cover = candidate_cover
    from . import style as style_pkg
    # Owner's remembered choice for this song (/revise stil …) beats cover and music.
    from . import songstyle
    style_override = profile.get("style", "auto")
    if style_override in ("", "auto") and songstyle.for_track(track.id):
        style_override = songstyle.for_track(track.id)
        print(f"Style remembered for this song: {style_override}")
    style_decision = style_pkg.analyze(cover, override=style_override, features=features)
    style_name = style_decision.get("style")
    style_variant = style_decision.get("variant")
    print(f"Style: {style_pkg.label(style_decision)} ({style_decision.get('basis')})")
    # Styles only nudge v4: lane weights blended 50/50 with the owner's profile.
    style_profile = validate_profile(dict(profile, weights=style_pkg.blended_weights(
        profile["weights"], style_name, style_variant)))
    profile_queries = choose_shots(style_profile, track_id=track.id, mood=features.mood,
                                   energy=features.energy, limit=3, run_key=edition)
    cover_choice = {"method": "disabled", "queries": [], "lanes": []}
    if cover is not None:
        from .curation import cover_queries
        cover_choice = cover_queries(cover, style_profile["weights"], run_key=edition)
    if cover_choice.get("queries"):
        from .curation import merge_queries
        keywords = merge_queries(cover_choice, profile_queries)
        print(f"Cover-led search ({cover_choice['method']}): {cover_choice['queries']}")
    else:
        keywords = profile_queries
    trend_signals = {"status": "disabled", "topics": []}
    if os.getenv("CARLECOOL_TRENDS", "false").lower() in ("true", "1", "on"):
        from .trend_signals import fetch_signals, apply_trend
        trend_signals = fetch_signals()
        keywords = apply_trend(keywords, trend_signals)
    # Fixed style word lists lead the search (the cover-derived phrases often matched
    # nothing, e.g. "guitar wood grain notebook paper", and drifted off-style); one
    # cover/profile phrase stays as the fifth+1 lane.
    style_words = style_pkg.search_queries(style_decision, run_key=edition)
    if style_words:
        keywords = style_words + [k for k in keywords if k not in style_words][:1]
    print(f"Video search phrases: {keywords}")
    candidates = gather_videos(config.coverr_key, features.mood, recent, wanted=32, keywords=keywords,
                               max_lanes=len(keywords), exact=style_pkg.search_ladders(style_words))
    # Across Reels: clips from the last MEMORY_REELS previews are only used when there are
    # not enough fresh ones (no extra Coverr requests: same search, re-ordered).
    long_memory = recent_video_ids(previews, limit=MEMORY_REELS)
    fresh = [v for v in candidates if v.id not in long_memory]
    if len(fresh) >= 16:
        candidates = fresh
    else:
        candidates = fresh + [v for v in candidates if v.id in long_memory]
    print(f"Clip memory: {len(fresh)} fresh candidates, "
          f"{len(candidates) - len(fresh)} seen in the last {MEMORY_REELS} Reels kept as reserve")
    from .curation import rank_candidates
    style_fit: dict[str, float] = {}
    candidates, prerank = rank_candidates(candidates, cover, output_dir / "thumbs", keep=18,
                                          world=style_name, style_fit=style_fit,
                                          ref_world="night" if style_variant == "night" else style_name)
    if len(fresh) < 16:  # ranking must not pull stale clips in front of fresh ones
        candidates = ([v for v in candidates if v.id not in long_memory]
                      + [v for v in candidates if v.id in long_memory])
    if prerank:
        print(f"Pre-download ranking kept {len(prerank)} of the candidate clips")
    from .render import is_portrait
    from .video import MIN_PORTRAIT_CLIPS, allow_landscape
    selected = []
    paths = []
    # Within a Reel: one clip per shot. Count the shots first and fetch enough clips
    # (signature + archival clips cover ~4–6 of them).
    from .render import plan_intervals
    try:
        planned_shots = len(plan_intervals(features, reel_length, style_pkg.pace_for(profile["pace"], style_name)))
    except Exception:
        planned_shots = 14
    stock_limit = max(6, min(14, planned_shots - 5))  # + signature shots, 2 Prelinger, 1 Wikimedia
    print(f"Planned shots: {planned_shots}; fetching up to {stock_limit} stock clips")
    landscape_reserve = []  # downloaded landscape clips, used only to fill up
    from .dedupe import Library
    seen_pictures = Library()

    def unique(video, path) -> bool:
        """False (and file removed) when the clip shows the same picture as one we have."""
        twin, sig = seen_pictures.duplicate_of(Path(path))
        if twin is not None:
            print(f"Clip skipped (same picture as {twin}): {video.id}")
            if video.source != "owned":
                Path(path).unlink(missing_ok=True)
            return False
        seen_pictures.add(video.id, sig)
        return True

    def accept(video, path):
        if video.source == "coverr":
            record_coverr_download(video.id, config.coverr_key)
        selected.append(video)
        paths.append(path)

    from .video import coverr_blocked
    for video in candidates:
        if len(paths) >= stock_limit:
            break
        if coverr_blocked() and video.source == "coverr":
            print(f"Coverr {coverr_blocked()} — remaining Coverr candidates skipped")
            break
        try:
            target = output_dir / f"stock_{len(paths) + len(landscape_reserve):02d}.mp4"
            path = fetch_owned_stock(video, target) if video.source == "owned" else download_video(video.url, target)
            if not unique(video, path):
                continue
            if is_portrait(path):
                accept(video, path)
            elif allow_landscape():
                landscape_reserve.append((video, path))
            else:
                print(f"Clip skipped (not portrait): {video.id}")
                if video.source != "owned":
                    path.unlink(missing_ok=True)
        except Exception as exc:
            from .video import describe_error
            print(f"Clip unavailable (skipped): {video.id}: {describe_error(exc)}")
    # Free archival footage: public-domain Prelinger home movies (analog Americana) for
    # both worlds; NASA only when a Rubin cover clearly shows space. Never a bookend.
    archival = []
    if style_name:
        from .archives import fetch_archival
        prompt = style_decision.get("prompt") or ""
        archive_key = ("rubin" if style_name == "rubin" and any(w in prompt for w in ("planet", "space", "earth"))
                       else "lana")
        # Owner: the Prelinger home movies are a highlight → up to 4 films per Reel (one
        # segment each); films from the last 12 Reels are skipped so the pool lasts.
        archival = fetch_archival(archive_key, set(recent_video_ids(previews, limit=12)) | recent,
                                  output_dir / "archive", run_key=edition,
                                  max_clips=int((style_pkg.look(style_name) or {}).get("archive_films") or PRELINGER_CLIPS),
                                  attempts=14)
        from .wikimedia import fetch_wikimedia
        archival += fetch_wikimedia(style_name, set(recent_video_ids(previews, limit=30)) | recent,
                                    output_dir / "wikimedia", run_key=edition, max_clips=1)
    portrait_count = len(paths)
    portrait_paths = set(paths)
    # Landscape only fills up a thin portrait supply, and always after the portrait clips.
    if portrait_count < MIN_PORTRAIT_CLIPS:
        # Fill up to the normal clip count so a landscape-only catalogue still gives variety.
        fill_up(landscape_reserve, accept, lambda: len(paths) >= stock_limit)
    for video, path in landscape_reserve:
        if path not in paths and video.source != "owned":
            path.unlink(missing_ok=True)
    archival = [v for v in archival if unique(v, Path(v.path))]
    for video in archival:
        selected.append(video)
        paths.append(Path(video.path))
    print(f"Footage: {portrait_count} portrait + {len(paths) - portrait_count - len(archival)} landscape fill-in"
          f" + {len(archival)} archival clips")
    if not paths:
        raise RuntimeError("No licensed clips available; add assets/stock and manifest.json as fallback")
    # Optional AI shot: appended LAST and excluded from the opening/closing shot,
    # because it is short (2 s) and low resolution (512×768).
    if profile["ai_video"] and os.getenv("CARLECOOL_AI_VIDEO", "off") == "one":
        try:
            from .ai_video import generate_one
            ai_path = generate_one(style_pkg.AI_DIRECTION.get(style_name, keywords[0]),
                                   output_dir / "ai_experiment.mp4")
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
    # Strongest clip first: any regular stock clip may open (not archive films, AI or the
    # signature accents added below).
    opening_pool = {i for i, v in enumerate(selected) if v.source in ("coverr", "pexels", "owned")}
    opening_fit = {i: style_fit[v.id] for i, v in enumerate(selected) if v.id in style_fit}
    # Neither the AI shot nor a centre-cropped landscape clip may open or close the Reel.
    no_bookend = {i for i, v in enumerate(selected) if v.source == "ai"}
    no_bookend |= {i for i, path in enumerate(paths) if path not in portrait_paths and selected[i].source != "ai"}
    # Signature shots ADDED on top of the v4 footage (never replacing it).
    signature_slots: dict[str, int] = {}
    signature_info: dict[str, dict] = {}
    from . import signature
    if signature.enabled() and config.coverr_key:
        memory = recent_video_ids(previews, limit=signature.MEMORY_REELS)
        exclude = set(memory) | set(recent) | {v.id for v in selected}
        # Friends/couples, flag, car and Americana belong to BOTH worlds (owner: also in Rubin); priority order, and the
        # search stops once enough roles are filled (Coverr allows ~50 requests/hour).
        # Learned from platform numbers: roles that clearly help come first (also for the
        # ~40 % placement cap), roles that clearly hurt come last.
        signature.PRIORITY = performance.role_priority(signature.DEFAULT_PRIORITY, perf_model)
        roles = [(role, signature.queries_for(role, style_name, style_variant))
                 for role in signature.PRIORITY if role != "motif"]
        roles.append(("motif", style_pkg.motif_queries(style_decision)))
        for role, queries in roles:
            if not queries or len(signature_slots) >= signature.MAX_ROLES:
                continue
            if coverr_blocked() and role != "skater":
                print(f"Signature {role}: skipped (Coverr {coverr_blocked()})")
                continue
            # Fixed order where the first query matters (flag, Porsche), rotated otherwise.
            ordered = (list(queries) if role in ("motif", "flag")
                       else signature.car_order(queries, edition) if role == "car"
                       else signature._rotate(tuple(queries), f"{edition}|{role}"))
            found = signature.rank(role, signature.search_slot(config.coverr_key, ordered, exclude=exclude,
                                                               role=role), output_dir / "thumbs",
                                    world="night" if style_variant == "night" else style_name)
            for video in found[:3]:
                target = output_dir / f"sig_{role}.mp4"
                try:
                    path = download_video(video.url, target)
                    if role == "skater":
                        face = signature.largest_face_ratio(path)
                        if face > signature.FACE_MAX_HEIGHT:
                            print(f"Signature skater {video.id} rejected: visible face ({face:.0%} of frame)")
                            path.unlink(missing_ok=True)
                            continue
                    if not unique(video, path):
                        continue
                    record_coverr_download(video.id, config.coverr_key)
                    selected.append(video)
                    paths.append(path)
                    signature_slots[role] = len(paths) - 1
                    no_bookend.add(len(paths) - 1)
                    signature_info[role] = {"id": video.id, "query": video.query}
                    print(f"Signature {role}: {video.id} ('{video.query}')")
                    break
                except Exception as exc:
                    print(f"Signature {role} clip skipped: {video.id}: {type(exc).__name__}")
            else:
                if role == "skater" and role not in signature_slots:
                    # Coverr empty or throttled: free Wikimedia skateboarding footage.
                    from .wikimedia import fetch_wikimedia
                    for video in fetch_wikimedia("skater", exclude, output_dir / "wikimedia",
                                                 run_key=edition, max_clips=1):
                        if signature.largest_face_ratio(Path(video.path)) > signature.FACE_MAX_HEIGHT:
                            print(f"Signature skater {video.id} rejected: visible face")
                            continue
                        if not unique(video, Path(video.path)):
                            continue
                        selected.append(video)
                        paths.append(Path(video.path))
                        signature_slots[role] = len(paths) - 1
                        no_bookend.add(len(paths) - 1)
                        signature_info[role] = {"id": video.id, "query": video.query}
                        print(f"Signature skater: {video.id} (Wikimedia)")
                if role not in signature_slots:
                    print(f"Signature {role}: no suitable clip this time")
    check_quality(paths, planned_shots, signature_slots)
    from . import masterstore
    from .naming import artist_name
    from .titlecard import enabled as title_card_enabled
    title_card = (artist_name(), track.title) if title_card_enabled() else None
    out = output_dir / f"carlecool_{track.id}.mp4"
    try:
        details = render_reel(audio, paths, features, out, reel_length,
                              pace=style_pkg.pace_for(profile["pace"], style_name), analog=profile["analog"], cover=cover,
                              no_bookend=no_bookend, fit_email=not masterstore.configured(),
                              title_card=title_card,
                              style_grade=style_pkg.grade_filters(style_name, style_variant),
                              signature_slots=signature_slots, look=style_pkg.look(style_name),
                              opening_pool=opening_pool, opening_fit=opening_fit)
    finally:
        if cover is not None:
            cover.unlink(missing_ok=True)
    from . import captions
    caption_copy = captions.variant(style_name, style_variant, edition)
    if performance.ask_question(perf_model, bool(caption_copy["question"])) != bool(caption_copy["question"]):
        caption_copy["question"] = (captions.QUESTIONS[0] if not caption_copy["question"] else "")
    reel_facts = {
        "style": style_name, "variant": style_variant, "style_basis": style_decision.get("basis"),
        "length_s": round(reel_length, 2), "length_bucket": performance.bucket(reel_length),
        "scenes": details.get("scenes"), "bpm": features.bpm,
        "roles": sorted(r for r, n in (details.get("signature_shots") or {}).items() if n),
        "opening_clip": (selected[details["opening_clip"]].id if details.get("opening_clip") is not None else None),
        "archival": sum(1 for v in selected if v.source in ("prelinger", "nasa", "wikimedia")),
        "question": bool(caption_copy["question"]), "hashtags": caption_copy["hashtags"],
    }
    metadata = {
        "track_id": track.id, "title": track.title, "permalink": track.permalink_url,
        "song_label": song_label(track.title),
        "features": vars(features), "video_ids": [v.id for v in selected],
        "footage_sources": [{"id": v.id, "provider": v.source, "title": v.title} for v in selected],
        "caption": caption_for(track, selected, caption_copy), "caption_variant": caption_copy,
        "reel_facts": reel_facts, "length_bucket": reel_facts["length_bucket"],
        "performance_summary": performance.summary(perf_model),
        "search_keywords": keywords,
        "visual_direction": editorial_brief(features.mood, features.energy, features.bpm),
        "creative_profile": profile,
        "cover_matching": cover_matching,
        "style": {"name": style_name, "label": style_pkg.label(style_decision),
                  **{k: v for k, v in style_decision.items() if k != "style"}},
        "signature": signature_info,
        "music_analysis": {"analyzer": features.analyzer, "reel_length": reel_length,
                           "hook_at": features.hook_at, "beats": len(features.beats),
                           "downbeats": len(features.downbeats)},
        "trend_signals": trend_signals,
        "output": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), **details,
    }
    (output_dir / "reel_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if details.get("opening_clip") is not None:
        print(f"Opening clip (strongest): {selected[details['opening_clip']].id}"
              f" '{selected[details['opening_clip']].title[:50]}'")
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
