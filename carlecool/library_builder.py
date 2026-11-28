"""Footage library builder (owner goal, 28 Nov: "hoch professionelle Videos … ohne Kosten").

The biggest limit of every Reel is the material of the day: one run sees ~20 search hits,
and after the gates only a handful fit together. This off-peak job fills the footage
library between the Reels, for one director and its least-covered theme per run:

  search (Coverr, within a small budget; NARA where the theme wants archive films)
  → the same gates as a Reel (block lists, style gate, motif relevance, reference floor)
  → download → Shot DNA → keep only good, on-brief windows → catalogue + Actions cache.

The next Reels of that director then pick from a growing pool of proven clips (library.py)
— no extra requests at Reel time. Free: public-repo Actions minutes, Coverr's free API
inside its hourly allowance (provider memory), NARA inside its monthly budget.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import os
from pathlib import Path

RUN_COVERR = 15          # Coverr requests per builder run (Reels keep the rest of the hour)
NEW_PER_RUN = 8          # new library clips per run at most
MIN_QUALITY = 0.45
MIN_REF = 0.24


def pick_target(library_data: dict, now: datetime | None = None) -> tuple[str, str]:
    """(director, theme): directors alternate by day half; the theme with fewest clips."""
    from . import directors, themes
    now = now or datetime.now(timezone.utc)
    names = directors.active() or ["lana"]
    director = names[(now.timetuple().tm_yday * 2 + (now.hour >= 12)) % len(names)]
    counts = Counter((e.get("director"), e.get("theme")) for e in (library_data.get("clips") or {}).values())
    theme_names = list(themes.THEMES.get(director, {}))
    theme = min(theme_names, key=lambda t: (counts[(director, t)], theme_names.index(t))) if theme_names else None
    return director, theme


def build(*, out_dir: Path = Path("output/library_build"), now: datetime | None = None) -> dict:
    from . import directors
    try:
        return _build(out_dir=out_dir, now=now)
    finally:
        directors.use(None)  # the director in use is process state: never leak it


def _build(*, out_dir: Path, now: datetime | None) -> dict:
    from . import directors, library, nara, providers, shot_analysis, stylegate, themes
    from . import video as video_mod
    from .curation import rank_candidates
    from .semantic import load_clip, semantic_enabled
    data = library.load()
    director, theme = pick_target(data, now)
    directors.use(director)
    d = directors.get(director) or {}
    world, variant = d.get("world"), d.get("variant")
    info = themes.get(world, variant, theme) or {}
    words = [w for w in info.get("words") or []][:6]
    print(f"Library build: {director} / {theme} — {words}")
    out_dir.mkdir(parents=True, exist_ok=True)
    known = set((data.get("clips") or {}).keys())
    added = 0
    report = {"director": director, "theme": theme, "added": 0, "coverr_requests": 0, "nara_calls": 0}
    clip = load_clip() if semantic_enabled() else None
    refs = None
    if clip is not None:
        from .stylegate import load_neighbors
        refs = load_neighbors(d.get("references") or director)
    key = os.getenv("COVERR_API_KEY", "")
    plan = providers.coverr_plan() if key else {"action": "skip", "budget": 0}
    if key and plan["action"] == "go":
        video_mod.COVERR_REQUESTS = 0
        video_mod.COVERR_MAX_REQUESTS = min(RUN_COVERR, int(plan["budget"]))
        cands = video_mod.search_coverr(key, "", known, wanted=40, keywords=words, max_lanes=len(words))
        cands = [c for c in cands if c.id not in known and not stylegate.blocked_words(c)
                 and not stylegate.flag_mismatch(c)]
        ranked, _ = rank_candidates(cands, None, out_dir / "thumbs", keep=NEW_PER_RUN * 2, world=world,
                                    ref_world=d.get("references"))
        for v in ranked:
            if added >= NEW_PER_RUN or video_mod.coverr_blocked():
                break
            if v.source != "coverr" or not v.url:
                continue
            try:
                raw = video_mod.download_video(v.url, out_dir / f"raw_{v.id}.mp4")
                dna = shot_analysis.analyze(raw, clip=clip, references=refs)
                ok = (float(dna.get("quality") or 0) >= MIN_QUALITY
                      and (dna.get("ref_score") is None or float(dna["ref_score"]) >= MIN_REF)
                      and not (variant == "night" and float(dna.get("luma") or 0) > 0.45))
                if ok:
                    cut = shot_analysis.cut_to_window(raw, dna, out_dir / f"win_{v.id}.mp4")
                    video_mod.record_coverr_download(v.id, key)
                    if library.add(data, v, Path(cut), dna, director=director, theme=theme,
                                   run_id=os.getenv("GITHUB_RUN_ID")):
                        added += 1
                        print(f"Library: + {v.id} '{v.title[:50]}' (quality {dna.get('quality')}, ref {dna.get('ref_score')})")
                else:
                    print(f"Library: skipped {v.id} (quality {dna.get('quality')}, ref {dna.get('ref_score')})")
                raw.unlink(missing_ok=True)
            except Exception as exc:  # one bad clip never stops the build
                print(f"Library: {v.id} unavailable: {type(exc).__name__}")
        report["coverr_requests"] = video_mod.COVERR_REQUESTS
        providers.record(video_mod.COVERR_REQUESTS, video_mod.coverr_blocked(), os.getenv("GITHUB_RUN_ID"))
    else:
        print(f"Library build: Coverr {plan['action']} — skipped this run")
    # Wikimedia Commons (PD / CC0 / CC BY videos) by the theme's own words — free, no budget issue
    from . import wikimedia
    wm = wikimedia.fetch_theme([w for w in words if w not in ("american flag",)], set(known), out_dir / "wm",
                               night=variant == "night", run_key=os.getenv("GITHUB_RUN_ID", "lb"),
                               max_clips=max(0, NEW_PER_RUN - added))
    for v in wm:
        dna = shot_analysis.analyze(Path(v.path), clip=clip, references=refs)
        if float(dna.get("quality") or 0) >= MIN_QUALITY and library.add(
                data, v, Path(v.path), dna, director=director, theme=theme, run_id=os.getenv("GITHUB_RUN_ID")):
            added += 1
    archive = int(info.get("archive") or 0)
    if nara.api_key() and archive > 0:
        clips, calls = nara.fetch_nara(director, set(known), out_dir / "nara", run_key=os.getenv("GITHUB_RUN_ID", "lb"),
                                       max_clips=min(2, archive))
        report["nara_calls"] = calls
        nara.record(calls, os.getenv("GITHUB_RUN_ID"))
        for v in clips:
            dna = shot_analysis.analyze(Path(v.path), clip=clip, references=refs)
            if library.add(data, v, Path(v.path), dna, director=director, theme=theme, run_id=os.getenv("GITHUB_RUN_ID")):
                added += 1
    library.save(data)
    report["added"] = added
    print(f"Library build done: {added} new clips for {director}/{theme}; "
          f"{len(data.get('clips') or {})} catalogued")
    return report


def main() -> int:
    try:
        build()
    except Exception as exc:  # bookkeeping job: never fail loudly
        print("Library build failed:", type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
