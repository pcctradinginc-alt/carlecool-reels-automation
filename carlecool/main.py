"""Preview-only CLI. Publication requires separate owner-approved Gmail workflow."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

from . import licences

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
    archives_used = list(dict.fromkeys((v.creator_name or "Prelinger Archives (public domain)")
                                       .replace(" (public domain)", "")
                                       for v in videos if v.source == "prelinger"))
    if archives_used:
        caption += "🎬 Archive footage: " + ", ".join(archives_used) + ", public domain (archive.org)\n"
    if any(v.source == "nara" for v in videos):
        caption += "🎬 Archive footage: U.S. National Archives (catalog.archives.gov), public domain\n"
    tags = captions.tail(copy) if copy else "#carlecool #instrumental #electronic #rap #producer"
    return caption.rstrip() + "\n\n" + tags


MAX_PER_MOTIF = 2


def themes_enabled() -> bool:
    """One theme per Reel (owner, 26 Nov); CARLECOOL_THEMES=off restores the word mix."""
    return os.getenv("CARLECOOL_THEMES", "on").strip().lower() not in ("off", "false", "0", "no")


ARCHIVE_BONUS = 2  # extra archive films when the portrait stock is thin
NARA_CLIPS = 2  # National Archives segments per Reel (27 Nov)


def motif_of(video) -> str:
    """Search word a stock clip came from (its motif); "" for clips without one."""
    query = (getattr(video, "query", "") or "").strip().lower()
    return "" if video.source in ("owned", "ai") or query.startswith("wikimedia:") else query


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


def classic_pipeline() -> bool:
    return os.getenv("CARLECOOL_PIPELINE", "").strip().lower() == "classic"


def analyse_shots(selected, paths: list, output_dir: Path, ref_world: str | None) -> list[dict | None]:
    """Shot DNA per clip (shot_analysis.py); each path is replaced by its best window."""
    from . import shot_analysis
    from .semantic import load_clip, semantic_enabled
    from .stylegate import load_neighbors
    clip = load_clip() if semantic_enabled() else None
    refs = load_neighbors(ref_world) if clip is not None else None
    out: list[dict | None] = []
    for i, path in enumerate(paths):
        try:
            dna = shot_analysis.cached_analyze(Path(path), clip=clip, references=refs)
            cut = shot_analysis.cut_to_window(Path(path), dna, output_dir / f"window_{i:02d}.mp4")
            if Path(cut) != Path(path):
                print(f"Best window of {selected[i].id}: {dna['best_start']:.1f}s + {dna['best_length']:.1f}s"
                      f" (quality {dna.get('quality')}, {dna.get('shot_size') or '?'})")
                paths[i] = Path(cut)
            out.append(dna)
        except Exception as exc:  # analysis is an improvement, never a reason to fail
            print(f"Shot analysis skipped for {selected[i].id}: {type(exc).__name__}")
            out.append(None)
    return out


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
    from . import video as video_provider
    video_provider.COVERR_REQUESTS = 0
    COVERR_BLOCK = video_provider.COVERR_BLOCK
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
    if int(perf_model.get("observations", 0)) < 60:
        perf_model = {}  # observation only until a meaningful sample exists
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
    rotated = None
    if (style_override in ("", "auto") and style_pkg.mode() == "auto" and style_pkg.rotation_enabled()):
        # Owner, 25 Nov: Lana / Rubin / Night in even rotation instead of cover detection.
        rotated = style_pkg.rotate_style(previews, edition)
        style_override = rotated
    style_decision = style_pkg.analyze(cover, override=style_override, features=features)
    from . import directors
    if rotated:
        if (directors.get(rotated) or {}).get("variant") != "night":
            style_decision["variant"] = None  # a dark cover no longer turns Lana into Night
        style_decision["basis"] = f"rotation ({rotated})"
    style_name = style_decision.get("style")
    style_variant = style_decision.get("variant")
    # Creative Director (27 Nov): one file in directors/ steers themes, search, look, effects.
    director = style_decision.get("director") or directors.for_style(style_name, style_variant)
    directors.use(director)
    style_decision["director"] = directors.current()
    ref_world = ((directors.get(director) or {}).get("references")
                 or ("night" if style_variant == "night" else style_name))
    print(f"Style: {style_pkg.label(style_decision)} ({style_decision.get('basis')})"
          f" · Creative Director: {directors.current() or 'legacy'}")
    # Owner, 26 Nov: ONE theme per Reel (search words, roles, archive share, text line).
    from . import themes
    theme = themes.choose(style_name, style_variant, previews, edition, features) if themes_enabled() else None
    theme_fit = None
    if theme:
        classes = themes.music_classes(features)
        fit = theme_fit = themes.music_fit(themes.key_for(style_name, style_variant), theme, classes)
        print(f"Theme: {theme} ({themes.get(style_name, style_variant, theme)['label']}) — music {classes}"
              f", fit {fit if fit is None else round(fit, 2)}; timbre {getattr(features, 'timbre_hz', 0):.0f} Hz,"
              f" percussive {getattr(features, 'percussive', 0):.2f}, dynamics {getattr(features, 'dynamics', 0):.2f}")
    # Phase 1 (audit A1): with a theme the search words come from the theme alone; the
    # profile / cover / trend phrases were computed and then thrown away — now skipped.
    style_words = (themes.words(style_name, style_variant, theme, edition, style_pkg.SEARCH_LANES)
                   if theme else style_pkg.search_queries(style_decision, run_key=edition))
    cover_choice = {"method": "theme" if theme else "disabled", "queries": [], "lanes": []}
    trend_signals = {"status": "not used (theme-led search)" if theme else "disabled", "topics": []}
    if theme:
        keywords = style_words  # no off-theme cover/profile phrase (Reel #54)
        if not classic_pipeline():
            # Phase 2: the film idea leads — the theme's dominant motifs are searched first
            from .creative_director import search_order
            dominant = list((themes.get(style_name, style_variant, theme) or {}).get("words") or [])[:4]
            keywords = search_order(dominant, keywords)
    else:
        # Without a theme (theme rotation off): profile lanes + cover phrases as before.
        style_profile = validate_profile(dict(profile, weights=style_pkg.blended_weights(
            profile["weights"], style_name, style_variant)))
        keywords = choose_shots(style_profile, track_id=track.id, mood=features.mood,
                                energy=features.energy, limit=3, run_key=edition)
        if cover is not None:
            from .curation import cover_queries, merge_queries
            cover_choice = cover_queries(cover, style_profile["weights"], run_key=edition)
            if cover_choice.get("queries"):
                keywords = merge_queries(cover_choice, keywords)
                print(f"Cover-led search ({cover_choice['method']}): {cover_choice['queries']}")
        if os.getenv("CARLECOOL_TRENDS", "false").lower() in ("true", "1", "on"):
            from .trend_signals import fetch_signals, apply_trend
            trend_signals = fetch_signals()
            keywords = apply_trend(keywords, trend_signals)
        if style_words:
            keywords = style_words + [k for k in keywords if k not in style_words][:1]
    print(f"Video search phrases: {keywords}")
    if config.coverr_key:
        apply_coverr_plan()
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
                                          ref_world=ref_world)
    if len(fresh) < 16:  # ranking must not pull stale clips in front of fresh ones
        candidates = ([v for v in candidates if v.id not in long_memory]
                      + [v for v in candidates if v.id in long_memory])
    if prerank:
        print(f"Pre-download ranking kept {len(prerank)} of the candidate clips")
    from .render import is_portrait
    from .video import MIN_PORTRAIT_CLIPS, allow_landscape, landscape_equal
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

    def unique(video, path, keep: bool = False) -> bool:
        """False (and file removed) when the clip shows the same picture as one we have."""
        twin, sig = seen_pictures.duplicate_of(Path(path))
        if twin is not None:
            print(f"Clip skipped (same picture as {twin}): {video.id}")
            if video.source != "owned" and not keep:
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
    from collections import Counter
    motif_count: Counter = Counter()  # Reel #46: five boats from one search word
    # Footage Library (package B, 27 Nov): proven clips of this director first — already
    # analysed and cut to their best window, no Coverr request (not a new download).
    from . import library
    footage_library = library.load()
    library_ids: set[str] = set()
    for video in ([] if classic_pipeline() else library.candidates(
            footage_library, director=directors.current(), theme=theme,
            exclude=set(long_memory) | set(recent), limit=int(stock_limit * library.LIBRARY_SHARE))):
        motif = motif_of(video)
        if motif and motif_count[motif] >= MAX_PER_MOTIF:
            continue
        if not unique(video, Path(video.path), keep=True):
            continue
        if motif:
            motif_count[motif] += 1
        selected.append(video)
        paths.append(Path(video.path))
        library_ids.add(video.id)
    if library_ids:
        print(f"Footage library: {len(library_ids)} proven clips "
              f"({len(footage_library.get('clips', {}))} catalogued)")
    candidates = [v for v in candidates if v.id not in library_ids]
    for video in candidates:
        if len(paths) >= stock_limit:
            break
        motif = motif_of(video)
        if motif and motif_count[motif] >= MAX_PER_MOTIF:
            print(f"Clip skipped (already {MAX_PER_MOTIF} clips of '{motif}'): {video.id}")
            continue
        if coverr_blocked() and video.source == "coverr":
            print(f"Coverr {coverr_blocked()} — Coverr candidate skipped; other sources remain eligible")
            continue
        try:
            target = output_dir / f"stock_{len(paths) + len(landscape_reserve):02d}.mp4"
            path = fetch_owned_stock(video, target) if video.source == "owned" else download_video(video.url, target)
            if not unique(video, path):
                continue
            if motif:
                motif_count[motif] += 1
            if is_portrait(path) or landscape_equal():
                accept(video, path)  # owner 25 Nov: landscape reframed / panned is fine
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
        # Reel #46: no portrait stock at all → 10 cropped landscape fillers. Then more
        # public-domain home movies (178 since 24 Nov) instead of random filler clips.
        films = int((style_pkg.look(style_name, style_variant) or {}).get("archive_films") or PRELINGER_CLIPS)
        if theme:  # sunny 1940s–70s home movies only where the theme is that kind of scene
            films = themes.archive_films(style_name, style_variant, theme, films)
        if films and len(paths) < MIN_PORTRAIT_CLIPS:
            films += ARCHIVE_BONUS
            print(f"Few portrait stock clips ({len(paths)}): up to {films} archive films")
        if films:
            archival = fetch_archival(archive_key, set(recent_video_ids(previews, limit=12)) | recent,
                                      output_dir / "archive", run_key=edition, max_clips=films,
                                      attempts=24)
            from .wikimedia import fetch_wikimedia
            archival += fetch_wikimedia(style_name, set(recent_video_ids(previews, limit=30)) | recent,
                                        output_dir / "wikimedia", run_key=edition, max_clips=1)
        else:
            print(f"Theme '{theme}': no archive footage")
    # U.S. National Archives Catalog (owner, 27 Nov): unrestricted public-domain films for
    # both directors, within the monthly API budget (nara.py).
    from . import nara
    if nara.api_key() and style_name:
        nara_clips, _calls = nara.fetch_nara(directors.current(),
                                             set(recent_video_ids(previews, limit=30)) | set(recent),
                                             output_dir / "nara", run_key=edition, max_clips=NARA_CLIPS)
        archival += nara_clips
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
    # Optional AI shot: appended LAST and excluded from the opening/closing shot,
    # because it is short (2 s) and low resolution (512×768).
    ai_mode = os.getenv("CARLECOOL_AI_VIDEO", "off")
    ai_facts = []
    if profile["ai_video"] and ai_mode in ("one", "multi") and os.getenv("AI_VIDEO_PUBLISH_LICENSE_CONFIRMED") != "true":
        print("AI footage skipped: production distribution permission is not confirmed")
        ai_facts.append({"status": "skipped", "reason": "distribution_permission_unconfirmed"})
        ai_mode = "off"
    if profile["ai_video"] and ai_mode in ("one", "multi"):
        from .ai_video import generate_one, AIUnavailable
        from .quality_gate import clip_metrics, ai_usable
        from .creative_director import ai_directions
        directions = ai_directions(style_name, style_variant, keywords, style_decision, edition)
        limit = 1 if ai_mode == "one" else (2 if reel_length < 21 else 3)
        for i, direction in enumerate(directions[:limit]):
            try:
                ai_path = generate_one(direction, output_dir / f"ai_experiment_{i}.mp4", timeout_seconds=190)
                metrics = clip_metrics(ai_path)
                if not ai_usable(metrics):
                    ai_facts.append({"index": i, "status": "rejected", "metrics": metrics})
                    continue
                if not unique(Video(f"ai-{edition}-{i}", "ai"), ai_path):
                    continue
                selected.append(Video(id=f"ai-{edition}-{i}", source="ai",
                                      title="LTX 2.3 original AI footage", path=str(ai_path)))
                paths.append(ai_path)
                ai_facts.append({"index": i, "status": "accepted", "metrics": metrics, "direction": direction})
            except Exception as exc:
                ai_facts.append({"index": i, "status": "unavailable", "reason": str(exc) if isinstance(exc, AIUnavailable) else type(exc).__name__})
                print("Free AI provider unavailable; no retries or paid fallback")
                break
    if not paths:
        raise RuntimeError("No usable footage available")
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
    from . import pexels
    if signature.enabled() and (config.coverr_key or pexels.configured()):
        memory = recent_video_ids(previews, limit=signature.MEMORY_REELS)
        exclude = set(memory) | set(recent) | {v.id for v in selected}
        # Friends/couples, flag, car and Americana belong to BOTH worlds (owner: also in Rubin); priority order, and the
        # search stops once enough roles are filled (Coverr allows ~50 requests/hour).
        # Learned from platform numbers: roles that clearly help come first (also for the
        # ~40 % placement cap), roles that clearly hurt come last.
        signature.PRIORITY = performance.role_priority(signature.DEFAULT_PRIORITY, perf_model)
        theme_roles = themes.roles(style_name, style_variant, theme) if theme else None
        roles = [(role, signature.queries_for(role, style_name, style_variant))
                 for role in signature.PRIORITY if role != "motif"
                 and (theme_roles is None or role in theme_roles)]
        if theme_roles is None:
            roles.append(("motif", style_pkg.motif_queries(style_decision)))
        for role, queries in roles:
            if not queries or len(signature_slots) >= signature.MAX_ROLES:
                continue
            # Fixed order where the first query matters (flag, Porsche), rotated otherwise.
            ordered = (list(queries) if role in ("motif", "flag")
                       else signature.car_order(queries, edition) if role == "car"
                       else signature._rotate(tuple(queries), f"{edition}|{role}"))
            pool = (signature.search_slot(config.coverr_key, ordered, exclude=exclude, role=role)
                    if config.coverr_key and not coverr_blocked() else [])
            if len(pool) < 4 and pexels.configured():
                from .stylegate import blocked_words, flag_mismatch
                alternatives = pexels.search_pexels(os.getenv("PEXELS_API_KEY", ""), ordered, exclude, wanted=8)
                pool.extend(v for v in alternatives if not blocked_words(v) and not flag_mismatch(v))
            found = signature.rank(role, pool, output_dir / "thumbs",
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
                    if video.source == "coverr":
                        record_coverr_download(video.id, config.coverr_key)
                    exclude.add(video.id)
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
    # Shot Intelligence (package B): Shot DNA of every clip, cut to its strongest window.
    # Owner verdicts 27 Nov (blind test: old preferred; #82 worse than #73): the "classic"
    # pipeline renders like the #73 code — no Shot DNA windows, no coherence re-order, one
    # storyboard, no library. CARLECOOL_PIPELINE=classic (repo variable or workflow input).
    shot_dna = ([None] * len(paths) if classic_pipeline()
                else analyse_shots(selected, paths, output_dir, ref_world))
    for i, video in enumerate(selected):
        if video.id not in library_ids and shot_dna[i]:
            library.add(footage_library, video, paths[i], shot_dna[i], director=directors.current(),
                        theme=theme, run_id=os.getenv("GITHUB_RUN_ID"))
    library.save(footage_library)
    from . import masterstore
    from .naming import artist_name
    from .titlecard import enabled as title_card_enabled
    title_card = (artist_name(), track.title) if title_card_enabled() else None
    out = output_dir / f"carlecool_{track.id}.mp4"
    from . import hooktext
    hook_line = hooktext.choose(style_name, style_variant, edition,
                                prefer=performance.preferred(perf_model, "text"),
                                lines=themes.lines(style_name, style_variant, theme) if theme else None)
    print(f"Text hook: {hook_line!r}" if hook_line else "Text hook: none (A/B test)")
    from . import reach
    hook_strategy = ("push" if classic_pipeline()
                     else reach.hook_strategy(edition, (directors.get(director) or {}).get("hook_strategies")))
    print(f"Hook strategy: {hook_strategy}")
    # Phase 1: one Creative Plan records every creative decision and its reason (reproducible).
    from .creative_director import build_plan
    creative_plan = build_plan(director=directors.current(), style_decision=style_decision, theme=theme,
                               features=features, length=reel_length, keywords=list(keywords),
                               roles=list(signature_slots), hook_line=hook_line, hook_strategy=hook_strategy,
                               pipeline="classic" if classic_pipeline() else "cinematic",
                               music_fit=theme_fit, length_reason=str(length_choice.get("reason")))
    print(creative_plan.summary())
    def render_variant(rank: int) -> dict:
        return render_reel(audio, paths, features, out, reel_length,
                           pace=style_pkg.pace_for(profile["pace"], style_name), analog=profile["analog"], cover=cover,
                           no_bookend=no_bookend, fit_email=not masterstore.configured(),
                           title_card=title_card,
                           style_grade=style_pkg.grade_filters(style_name, style_variant),
                           signature_slots=signature_slots, look=style_pkg.look(style_name, style_variant),
                           opening_pool=opening_pool, opening_fit=opening_fit, hook_text=hook_line,
                           ref_world=ref_world, hook_strategy=hook_strategy, dna=shot_dna, variant_rank=rank,
                           hdr_sources={i: d["hdr"] for i, d in enumerate(shot_dna) if d and d.get("hdr")},
                           soft_sources={i for i, v in enumerate(selected) if v.source in ("coverr", "pexels")})
    from . import critic
    try:
        details = render_variant(0)
        verdict = critic.review(out, details)
        print(f"Visual critic: {verdict['score']} {verdict['issues'] or 'no issues'}")
        if verdict["retry"] and len(details.get("storyboards") or []) > 1:
            # Package D: one re-edit with the second-best storyboard; the better verdict wins.
            first = out.with_name("first_edit.mp4")
            os.replace(out, first)
            second = render_variant(1)
            second_verdict = critic.review(out, second)
            print(f"Visual critic (re-edit): {second_verdict['score']} {second_verdict['issues'] or 'no issues'}")
            if second_verdict["score"] > verdict["score"]:
                details, verdict = second, second_verdict
                first.unlink(missing_ok=True)
            else:
                os.replace(first, out)
            verdict["re_edited"] = True
        details["critic"] = verdict
    finally:
        if cover is not None:
            cover.unlink(missing_ok=True)
    from .quality_gate import inspect_reel
    quality = inspect_reel(out, details, reel_length)
    if quality["errors"]:
        raise QualityTooLow("Final master: " + "; ".join(quality["errors"]))
    from . import captions
    caption_copy = captions.variant(style_name, style_variant, edition)
    if performance.ask_question(perf_model, bool(caption_copy["question"])) != bool(caption_copy["question"]):
        caption_copy["question"] = (captions.QUESTIONS[0] if not caption_copy["question"] else "")
    reel_facts = {
        "style": style_name, "variant": style_variant, "style_basis": style_decision.get("basis"),
        "director": directors.current(), "hook_strategy": hook_strategy,
        "pipeline": "classic" if classic_pipeline() else "cinematic", "library_clips": len(library_ids),
        "coherence": details.get("coherence"),
        "critic": {k: details.get("critic", {}).get(k) for k in ("score", "issues", "re_edited")},
        "storyboard": details.get("variant_rank"),
        "length_s": round(reel_length, 2), "length_bucket": performance.bucket(reel_length),
        "scenes": details.get("scenes"), "bpm": features.bpm,
        "roles": sorted(r for r, n in (details.get("signature_shots") or {}).items() if n),
        "opening_clip": (selected[details["opening_clip"]].id if details.get("opening_clip") is not None else None),
        "archival": sum(1 for v in selected if v.source in ("prelinger", "nasa", "wikimedia")),
        "question": bool(caption_copy["question"]), "hashtags": caption_copy["hashtags"],
        # hook facts for the learning system (25 Nov)
        "text_hook": bool(details.get("hook_text")), "hook_line": details.get("hook_text") or "",
        "theme": theme,
        "hook_at": round(float(getattr(features, "hook_at", 0.0) or 0.0), 2),
        "first_shot_s": details.get("first_shot_s"),
        # 27 Nov: reach effects (moving camera, opening push, flash cuts) — compare views before/after
        "reach_fx": bool(details.get("moving_shots")),
        "opening_source": (selected[details["opening_clip"]].source if details.get("opening_clip") is not None else None),
        "opening_motif": (selected[details["opening_clip"]].query if details.get("opening_clip") is not None else None),
    }
    metadata = {
        "track_id": track.id, "title": track.title, "permalink": track.permalink_url,
        "song_label": song_label(track.title),
        "features": vars(features), "video_ids": [v.id for v in selected],
        # licence proof per clip (+ search motif, so decisions.py can learn per motif)
        "footage_sources": [dict(licences.proof(v), motif=v.query or "",
                                 used=(i in set(details.get("used_sources") or range(len(selected)))),
                                 library=v.id in library_ids,
                                 shot_size=(shot_dna[i] or {}).get("shot_size") if i < len(shot_dna) else None,
                                 quality=(shot_dna[i] or {}).get("quality") if i < len(shot_dna) else None)
                            for i, v in enumerate(selected)],
        "caption": caption_for(track, selected, caption_copy), "caption_variant": caption_copy,
        "reel_facts": reel_facts, "length_bucket": reel_facts["length_bucket"],
        "creative_plan": dict(creative_plan.as_dict(), storyboard=details.get("slot_functions") or []),
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
        "trend_signals": trend_signals, "final_quality": quality, "ai_generation": ai_facts,
        "output": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), **details,
    }
    (output_dir / "reel_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if details.get("opening_clip") is not None:
        print(f"Opening clip (strongest): {selected[details['opening_clip']].id}"
              f" '{selected[details['opening_clip']].title[:50]}'")
    print(f"Rendered preview: {out} ({details['scenes']} beat-aligned scenes)")
    print("Preview mode: no Instagram API call, no state change")


def apply_coverr_plan(sleep=None) -> dict:
    """Respect Coverr's hourly limit ACROSS runs (data/provider-usage.json, 26 Nov)."""
    import time
    from . import providers, video as video_mod
    if os.getenv("CARLECOOL_PROVIDER_MEMORY", "on").strip().lower() in ("off", "false", "0", "no"):
        return {"action": "go"}
    plan = providers.coverr_plan()
    print(f"Coverr plan: {plan['action']} — {plan['reason']}")
    if plan["action"] == "wait":
        print(f"Waiting {plan['wait_s'] // 60} min for Coverr's hourly window instead of failing")
        (sleep or time.sleep)(plan["wait_s"])
    if plan["action"] == "skip":
        video_mod.COVERR_BLOCK["status"] = 429  # alternatives only; the quality gate decides
    else:
        video_mod.COVERR_MAX_REQUESTS = max(1, min(video_mod.COVERR_MAX_REQUESTS, plan["budget"]))
    return plan


def record_provider_usage() -> None:
    from . import nara, providers, video as video_mod
    if nara.api_key():
        try:
            nara.record(nara.RUN_CALLS, os.getenv("GITHUB_RUN_ID"))
        except OSError as exc:
            print("NARA usage not written:", type(exc).__name__)
    if not os.getenv("COVERR_API_KEY"):
        return
    try:
        # a real 403/429 from Coverr — not our own per-run budget running out
        real_block = (video_mod.coverr_blocked() if video_mod.COVERR_REQUESTS
                      and video_mod.COVERR_REQUESTS < video_mod.COVERR_MAX_REQUESTS else None)
        providers.record(video_mod.COVERR_REQUESTS, real_block, os.getenv("GITHUB_RUN_ID"))
    except OSError as exc:
        print("Provider usage not written:", type(exc).__name__)


def main():
    parser = argparse.ArgumentParser(description="CarleCool video pipeline")
    parser.add_argument("--mode", choices=["preview", "publish"], default="preview")
    args = parser.parse_args()
    try:
        process(publish=args.mode == "publish")
    finally:
        record_provider_usage()  # also after a failed run: the next run must know


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PIPELINE FAILED (fail closed): {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
