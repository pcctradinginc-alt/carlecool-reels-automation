"""Phase 0 baseline inputs (owner brief §17): one song's original audio and a FROZEN pool.

Pool = public-domain archive clips chosen with a fixed key (same clips every time) plus
the files of the footage library that are present. The list is written to pool.json so
later comparisons use exactly the same clips. No Coverr requests.

  python scripts/baseline_inputs.py --song "see clear" --out baseline/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", required=True)
    ap.add_argument("--out", default="baseline")
    ap.add_argument("--director", default="lana")
    ap.add_argument("--archive", type=int, default=6)
    a = ap.parse_args()
    from carlecool.audio import locate_original
    from carlecool.config import Settings
    from carlecool.main import pick_song
    from carlecool.soundcloud import fetch_tracks
    from carlecool import songpool, library, archives
    out = Path(a.out)
    pool = out / "pool"
    pool.mkdir(parents=True, exist_ok=True)
    config = Settings()
    tracks = fetch_tracks(config, pool=songpool.load())
    track = next(t for t in tracks if t.id == pick_song(tracks, a.song))
    audio = locate_original(track, out / "song.mp3")
    clips = []
    for v in archives.fetch_archival("lana", set(), out / "archive", run_key="baseline-v1",
                                     max_clips=a.archive, attempts=24):
        dest = pool / f"archive_{v.id}.mp4"
        shutil.copy(v.path, dest)
        clips.append({"file": dest.name, "id": v.id, "source": v.source, "title": v.title, "page": v.page_url})
    data = library.load()
    for cid, e in (data.get("clips") or {}).items():
        if e.get("director") == a.director and library.file_for(cid).is_file():
            dest = pool / f"library_{library.file_for(cid).name}"
            shutil.copy(library.file_for(cid), dest)
            clips.append({"file": dest.name, "id": cid, "source": e.get("source"), "title": e.get("title"),
                          "page": e.get("page_url")})
    (out / "pool.json").write_text(json.dumps({"song": track.title, "track_id": track.id, "audio": str(audio),
                                               "clips": clips}, indent=1), encoding="utf-8")
    print(f"Baseline inputs: '{track.title}', {len(clips)} pool clips")
    return 0 if len(clips) >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
