"""Phase 0 baseline: old vs new pipeline under IDENTICAL conditions (owner brief §17).

Same song excerpt (features computed once), same reel length, same footage pool, no
cover card, same final encoder settings of each version. Both renders are measured by the
SAME neutral instruments (critic measures, coherence on the same Shot DNA, loudness /
true peak, size, render time, peak memory). Output: report.json + report.md, and —
for blind rating — two labelled copies whose A/B assignment is stored only in the report.

  python scripts/compare_pipelines.py --audio song.mp3 --pool pool/ --old ../old --new . \
      --length 18 --director lana --out compare/

`--old` / `--new` are source trees (e.g. a `git worktree` of the baseline commit). Each
render runs in its own Python process with that tree on PYTHONPATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

RUNNER = r'''
import dataclasses, json, resource, sys, time
from pathlib import Path
src, spec = sys.argv[1], json.loads(sys.argv[2])
sys.path.insert(0, src)
from carlecool.analysis import AudioFeatures
from carlecool.render import render_reel
from carlecool import style
names = {f.name for f in dataclasses.fields(AudioFeatures)}
feat = AudioFeatures(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in spec["features"].items() if k in names})
clips = [Path(p) for p in spec["clips"]]
kw = dict(fit_email=False, look=style.look("lana"), style_grade=style.grade_filters("lana", spec.get("variant")),
          ref_world=spec["ref_world"], opening_pool=set(range(len(clips))))
dna = None
if spec["mode"] == "new":
    from carlecool import directors, shot_analysis
    from carlecool.semantic import load_clip, semantic_enabled
    from carlecool.stylegate import load_neighbors
    directors.use(spec["director"])
    kw["look"] = style.look("lana", spec.get("variant"))
    clip = load_clip() if semantic_enabled() else None
    refs = load_neighbors(spec["ref_world"]) if clip is not None else None
    dna = []
    for i, c in enumerate(list(clips)):
        d = shot_analysis.analyze(c, clip=clip, references=refs)
        clips[i] = shot_analysis.cut_to_window(c, d, Path(spec["work"]) / f"window_{i:02d}.mp4")
        dna.append(d)
    kw.update(dna=dna, hook_strategy="push")
t = time.time()
details = render_reel(Path(spec["audio"]), clips, feat, Path(spec["output"]), spec["length"], **kw)
details["render_seconds"] = round(time.time() - t, 1)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
details["max_rss_mb"] = round(rss / 1048576 if sys.platform == "darwin" else rss / 1024, 1)
print("RESULT " + json.dumps({k: details.get(k) for k in ("duration", "scenes", "edit_plan", "render_seconds",
      "max_rss_mb", "coherence", "storyboards", "loop_sealed", "dissolves", "moving_shots", "bw_shots")}))
'''


def loudness(path: Path) -> dict:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=300)
    out = {}
    for line in p.stderr.splitlines()[-30:]:
        line = line.strip()
        if line.startswith("I:"):
            out["integrated_lufs"] = float(line.split()[1])
        if line.startswith("Peak:"):
            out["true_peak_dbtp"] = float(line.split()[1])
    return out


def render(mode: str, src: Path, spec: dict) -> dict:
    env = dict(os.environ, PYTHONPATH=str(src))
    t = time.time()
    p = subprocess.run([sys.executable, "-c", RUNNER, str(src), json.dumps(dict(spec, mode=mode))],
                       capture_output=True, text=True, env=env, timeout=3600)
    if p.returncode:
        raise RuntimeError(f"{mode} render failed: {p.stderr[-2000:]}")
    line = next(x for x in p.stdout.splitlines() if x.startswith("RESULT "))
    res = json.loads(line[7:])
    res["wall_seconds"] = round(time.time() - t, 1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", default=".")
    ap.add_argument("--length", type=float, default=18.0)
    ap.add_argument("--director", default="lana")
    ap.add_argument("--out", default="compare")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(a.new).resolve()))
    from carlecool.analysis import analyze_audio
    from carlecool import critic, coherence, directors, shot_analysis
    from carlecool.cinematic import Shot
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    clips = sorted(str(p.resolve()) for p in Path(a.pool).glob("*.mp4"))
    if len(clips) < 4:
        raise SystemExit("pool needs at least 4 clips")
    features = analyze_audio(a.audio, a.length)
    d = directors.get(a.director) or {}
    base = {"features": {k: v for k, v in vars(features).items()}, "clips": clips, "audio": str(Path(a.audio).resolve()),
            "length": a.length, "director": a.director, "variant": d.get("variant"),
            "ref_world": d.get("references") or a.director}
    results = {}
    for mode, src in (("old", Path(a.old).resolve()), ("new", Path(a.new).resolve())):
        work = out / mode
        work.mkdir(exist_ok=True)
        spec = dict(base, output=str((work / "reel.mp4").resolve()), work=str(work.resolve()))
        res = render(mode, src, spec)
        res.update(loudness(work / "reel.mp4"))
        res["size_mb"] = round((work / "reel.mp4").stat().st_size / 1e6, 2)
        results[mode] = res
    # one neutral instrument for both: DNA of the ORIGINAL pool clips, the critic on the files
    pool_dna = [shot_analysis.analyze(Path(c)) for c in clips]
    for mode, res in results.items():
        plan = res.get("edit_plan") or []
        shots = [Shot(int(s["source_index"]), float(s["source_offset"]), float(s["duration"])) for s in plan]
        res["coherence_neutral"] = coherence.reel_coherence(shots, pool_dna)
        res["critic"] = critic.review(out / mode / "reel.mp4", dict(res, coherence=res["coherence_neutral"]))
        res.pop("edit_plan", None)
    # blind copies: A/B assignment only in the report
    rng = random.Random(hashlib.sha256((a.audio + str(a.length)).encode()).hexdigest())
    order = ["old", "new"]
    rng.shuffle(order)
    blind = {}
    for label, mode in zip("AB", order):
        target = out / f"blind_{label}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out / mode / "reel.mp4"), "-c", "copy", str(target)],
                       check=True)
        blind[label] = mode
    report = {"song": Path(a.audio).name, "length": a.length, "director": a.director, "pool": len(clips),
              "excerpt_start": features.excerpt_start, "bpm": features.bpm, "results": results,
              "blind_key": blind}
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    rows = ["| measure | old | new |", "|---|---|---|"]
    for key in ("duration", "scenes", "render_seconds", "wall_seconds", "max_rss_mb", "size_mb", "integrated_lufs",
                "true_peak_dbtp", "coherence_neutral"):
        rows.append(f"| {key} | {results['old'].get(key)} | {results['new'].get(key)} |")
    rows.append(f"| critic score | {results['old']['critic']['score']} | {results['new']['critic']['score']} |")
    rows.append(f"| critic issues | {', '.join(results['old']['critic']['issues']) or '–'} | "
                f"{', '.join(results['new']['critic']['issues']) or '–'} |")
    (out / "report.md").write_text("\n".join([f"# Baseline: {report['song']} · {a.length}s · {a.director} · "
                                              f"{len(clips)} pool clips", ""] + rows) + "\n", encoding="utf-8")
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
