"""Storyboard choice + independent Visual Critic (owner's plan, package D, 27 Nov).

1. Three storyboards, keep the best (`plan_score`): render.py builds three candidate edits
   (different clip rotations, each ordered by the coherence engine) and scores them BEFORE
   rendering — coherence of the transitions, quality of the clip windows used, strength of
   the opening, variety of shot sizes, no repeated clips. Only the best one is rendered.

2. The Visual Critic (`review`) judges the RENDERED video, separately from the director:
   does it look monotonous, incoherent, over-processed, choppy, does the loop jump? It
   only reads the finished file (frames sampled at 4 fps) and the edit plan. When it finds
   a serious problem, main.py renders the second-best storyboard once and keeps the
   better verdict. The technical checks (black / frozen frames, audio, size) stay in
   quality_gate.py.

The thresholds are starting values. Every verdict is stored in reel_facts.critic so it
can be calibrated against the owner's publish / discard decisions (decisions.py).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

SAMPLE_FPS = 4
W, H = 54, 96
RETRY_BELOW = 0.55          # critic score that triggers one re-edit
SIZES = ("wide", "medium", "close", "detail")


def plan_score(shots, dna: list[dict | None]) -> dict:
    """Score of a storyboard before rendering (0..1, higher = better) with its parts."""
    from .coherence import reel_coherence
    n = len(shots)
    if n == 0:
        return {"total": 0.0}
    total_len = sum(s.duration for s in shots) or 1.0
    quality = [((dna[s.source_index] or {}).get("quality"), s.duration) for s in shots
               if s.source_index < len(dna)]
    known = [(q, d) for q, d in quality if q is not None]
    q_mean = sum(q * d for q, d in known) / sum(d for _, d in known) if known else 0.5
    opener = (dna[shots[0].source_index] or {}).get("quality") if shots[0].source_index < len(dna) else None
    sizes = [(dna[s.source_index] or {}).get("shot_size") for s in shots if s.source_index < len(dna)]
    pairs = [(a, b) for a, b in zip(sizes, sizes[1:]) if a and b]
    variety = sum(1 for a, b in pairs if a != b) / len(pairs) if pairs else 0.5
    runs = max((len(list(g)) for _, g in __import__("itertools").groupby(sizes) if _), default=1)
    if runs >= 3:
        variety *= 0.6  # three or more of the same shot size in a row
    distinct = len({s.source_index for s in shots}) / n
    coh = reel_coherence(shots, dna)
    parts = {"coherence": coh if coh is not None else 0.5, "quality": q_mean,
             "opening": opener if opener is not None else 0.5, "variety": variety, "distinct": distinct}
    weights = {"coherence": 0.4, "quality": 0.2, "opening": 0.15, "variety": 0.15, "distinct": 0.1}
    parts["total"] = round(sum(weights[k] * parts[k] for k in weights), 4)
    parts["seconds"] = round(total_len, 2)
    return parts


def _frames(path: Path):
    import numpy as np
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                            f"fps={SAMPLE_FPS},scale={W}:{H},format=rgb24", "-f", "rawvideo", "-"],
                           capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    size = W * H * 3
    count = len(p.stdout) // size
    if count < 4:
        return None
    return np.frombuffer(p.stdout[:count * size], dtype=np.uint8).reshape(count, H, W, 3).astype(np.float32) / 255


def review(path: Path, details: dict) -> dict:
    """Verdict on the rendered Reel: {"score", "issues", "retry", "measures"}."""
    import numpy as np
    issues: list[str] = []
    measures: dict[str, float] = {}
    frames = _frames(Path(path))
    plan = details.get("edit_plan") or []
    if frames is not None:
        mx, mn = frames.max(axis=3), frames.min(axis=3)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
        lum = frames @ np.array([0.299, 0.587, 0.114], np.float32)
        clipped = float(((lum > 0.985) | (lum < 0.02)).mean())
        measures.update(saturation=round(float(sat.mean()), 3), clipped=round(clipped, 3))
        if clipped > 0.25:
            issues.append("over-processed: crushed blacks / blown highlights")
        if float(sat.mean()) > 0.62:
            issues.append("over-processed: oversaturated")
        luma = frames @ np.array([0.299, 0.587, 0.114], np.float32)
        lab_means = frames.reshape(len(frames), -1, 3).mean(axis=1)
        # monotony: the picture hardly changes over the whole Reel
        spread = float(np.std(luma.reshape(len(luma), -1).mean(axis=1)) + np.std(lab_means, axis=0).mean())
        measures["visual_spread"] = round(spread, 4)
        step = SAMPLE_FPS  # frames one second apart
        change = float(np.abs(luma[step:] - luma[:-step]).mean()) if len(luma) > step else 0.0
        measures["change_per_second"] = round(change, 4)
        if spread < 0.02 and change < 0.04:
            issues.append("monotonous: the picture barely changes")
        # loop: last frame vs first frame
        jump = float(np.abs(luma[-1] - luma[0]).mean())
        measures["loop_jump"] = round(jump, 3)
        if jump > 0.22 and not details.get("loop_sealed"):
            issues.append("loop jumps at the restart")
    else:
        issues.append("critic could not read the video")
    if plan:
        short = sum(1 for s in plan if float(s.get("duration") or 0) < 0.45)
        if short:
            issues.append(f"choppy: {short} shot(s) under 0.45 s")
        srcs = [s.get("source_index") for s in plan]
        if any(a == b for a, b in zip(srcs, srcs[1:])):
            issues.append("the same clip twice in a row")
    coh = details.get("coherence")
    if coh is not None:
        measures["coherence"] = coh
        if coh < 0.45:
            issues.append("incoherent: scenes do not belong together")
    score = max(0.0, 1.0 - 0.18 * len(issues))
    if coh is not None:
        score = 0.7 * score + 0.3 * min(1.0, coh / 0.75)
    score = round(score, 3)
    serious = any(i.startswith(("incoherent", "monotonous", "over-processed", "the same clip")) for i in issues)
    return {"score": score, "issues": issues, "retry": serious or score < RETRY_BELOW, "measures": measures}
