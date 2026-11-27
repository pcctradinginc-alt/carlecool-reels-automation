"""CarleCool Footage Library (owner's plan, package B, 27 Nov): "Hochwertige, vorab geprüfte
Aufnahmen katalogisieren und wiederverwendbar machen — die Bibliothek wächst mit jeder
Produktion."

Every clip that passed the gates of a Reel (content block lists, style gate, de-dupe) is
stored with its Shot DNA (shot_analysis.py), its licence proof and the director / theme it
was found for:

* the catalogue — data/footage-library.json in the repository (metadata only, no media,
  no signed download URLs);
* the files — the clip's best window (H.264, CRF 16) in footage-cache/, kept between runs
  by the GitHub Actions cache (free, up to 10 GB per repository; pruned to MAX_FILES).

The next Reels of the same director take their best-matching library clips first: proven
material, no Coverr request (a reused file is not a new download), so each run can pick
from a growing pool instead of the ~17 fresh search hits of the day. Clips the owner
blocked, clips of discarded Reels and clips shown in the last Reels are skipped.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

PATH = Path("data/footage-library.json")
CACHE = Path(os.getenv("CARLECOOL_LIBRARY_DIR", "footage-cache"))
MAX_FILES = 220            # ~10–15 MB each → well inside the free Actions cache
LIBRARY_SHARE = 0.5        # at most half of a Reel's stock clips come from the library
MIN_QUALITY = 0.35         # shot_analysis quality of the kept window
FIELDS = ("id", "source", "title", "query", "page_url", "licence", "licence_url", "creator_name",
          "creator_url", "width", "height")


def enabled() -> bool:
    return os.getenv("CARLECOOL_LIBRARY", "on").strip().lower() not in ("off", "false", "0", "no")


def load(path: Path = PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("clips"), dict) else {"version": 1, "clips": {}}
    except (OSError, ValueError):
        return {"version": 1, "clips": {}}


def save(data: dict, path: Path = PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_for(clip_id: str) -> Path:
    safe = "".join(ch for ch in str(clip_id) if ch.isalnum() or ch in "-_.")[:120]
    return CACHE / f"{safe}.mp4"


def add(data: dict, video, path: Path, dna: dict, *, director: str | None, theme: str | None,
        run_id: str | None) -> bool:
    """Catalogue one clip (already cut to its best window) and keep its file in the cache."""
    if getattr(video, "source", "") in ("owned", "ai") or not dna:
        return False
    if dna.get("quality") is not None and float(dna["quality"]) < MIN_QUALITY:
        return False
    clips = data.setdefault("clips", {})
    entry = clips.get(str(video.id)) or {"added": _now(), "runs": []}
    entry.update({k: getattr(video, k) for k in FIELDS if getattr(video, k, None) not in (None, "")})
    entry.update(director=director, theme=theme,
                 dna={k: v for k, v in dna.items() if k not in ("best_start", "best_length", "duration")},
                 seconds=dna.get("best_length") or dna.get("duration"))
    if run_id and run_id not in entry["runs"]:
        entry["runs"] = (entry["runs"] + [str(run_id)])[-20:]
    entry["last_used"] = _now()
    clips[str(video.id)] = entry
    target = file_for(video.id)
    if not target.is_file():
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-an", "-c:v", "libx264",
                            "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", str(target)],
                           check=True, capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            print("Library: file not cached:", video.id, type(exc).__name__)
            target.unlink(missing_ok=True)
    return True


def to_video(entry: dict):
    from .video import Video
    path = file_for(entry["id"])
    kw = {k: entry.get(k) for k in FIELDS if k in entry and k not in ("id", "source")}
    kw = {k: v for k, v in kw.items() if v is not None}
    width, height = int(entry.get("width") or 0), int(entry.get("height") or 0)
    return Video(str(entry["id"]), str(entry.get("source") or "coverr"), path=str(path),
                 vertical=height > width > 0, duration=float(entry.get("seconds") or 0), **kw)


def candidates(data: dict, *, director: str | None, theme: str | None, exclude: set[str],
               limit: int) -> list:
    """Best library clips for this Reel (file present, not excluded, not blocked / discarded)."""
    if not enabled() or limit <= 0:
        return []
    from .stylegate import blocked_words, flag_mismatch
    from . import decisions
    clip_scores, _ = decisions.scores()
    pool = []
    for cid, e in (data.get("clips") or {}).items():
        if cid in exclude or e.get("director") != director or not file_for(cid).is_file():
            continue
        if clip_scores.get(cid, 0) < 0:
            continue  # shown in a discarded Reel
        video = to_video(dict(e, id=cid))
        if blocked_words(video) or flag_mismatch(video):
            continue
        dna = e.get("dna") or {}
        score = float(dna.get("ref_score") or 0) + 0.5 * float(dna.get("quality") or 0)
        score += 0.05 if theme and e.get("theme") == theme else 0.0
        score += 0.03 * max(0, clip_scores.get(cid, 0))  # published before
        pool.append((score, video))
    pool.sort(key=lambda x: -x[0])
    # one clip per search motif first (variety), then the rest by score
    chosen, motifs = [], set()
    for score, v in pool:
        if len(chosen) >= limit:
            break
        if v.query and v.query in motifs:
            continue
        chosen.append(v)
        motifs.add(v.query)
    return chosen


def prune(data: dict) -> int:
    """Keep the MAX_FILES most recently used files; the catalogue entries stay."""
    if not CACHE.is_dir():
        return 0
    files = sorted(CACHE.glob("*.mp4"), key=lambda p: (data.get("clips", {}).get(p.stem, {}).get("last_used") or "",
                                                       p.stat().st_mtime), reverse=True)
    removed = 0
    for p in files[MAX_FILES:]:
        p.unlink(missing_ok=True)
        removed += 1
    return removed


def merge(remote: dict, local: dict) -> dict:
    clips = dict((remote.get("clips") or {}))
    for cid, e in (local.get("clips") or {}).items():
        old = clips.get(cid) or {}
        runs = list(dict.fromkeys((old.get("runs") or []) + (e.get("runs") or [])))[-20:]
        clips[cid] = {**old, **e, "runs": runs}
    return {"version": 1, "clips": clips}


def main() -> int:
    """`python -m carlecool.library` (workflow, always): prune the cache, commit the catalogue."""
    data = load()
    removed = prune(data)
    if removed:
        print(f"Library: {removed} old files removed from the cache")
    if not PATH.is_file() or os.getenv("GITHUB_ACTIONS") != "true":
        print("Library: nothing to record")
        return 0
    try:
        import base64
        from .performance import commit_json
        from .review import github_request
        try:
            item = github_request("GET", f"contents/{PATH.as_posix()}?ref=main")
            save(merge(json.loads(base64.b64decode(item["content"]).decode("utf-8")), data))
        except Exception as exc:
            print("Library: no merge with main:", type(exc).__name__)
        commit_json(PATH, "library: catalogue clips of this run [skip ci]")
        print(f"Library recorded: {len(load().get('clips', {}))} clips catalogued")
    except Exception as exc:  # never fail the run for bookkeeping
        print("Warning: library not stored:", type(exc).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
