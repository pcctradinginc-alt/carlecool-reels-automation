"""Style-specific editing language, decided per shot from the music (see style.LOOKS).

* Lana: soft dissolves into quiet passages (never on the hook: the drop stays a hard cut
  on the beat), subtle slow motion on quiet shots (only from ≥ 29 fps sources, so frames
  are never duplicated), warm light leaks at the start of some shots.
* Rubin: hard restrained cuts, a punch-in (closer framing) on the loudest passages, a
  slight per-shot exposure variation like real film stock.

Dissolve timing: the transition STARTS on the cut (on the beat) and lasts `dissolve` s;
the outgoing shot is rendered that much longer, so the total length is unchanged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess

DEFAULT_ENERGY = 0.55  # no beat data: treat as a medium passage


def shot_energy(features, start: float, duration: float) -> float:
    beats = list(getattr(features, "beats", ()) or ())
    energy = list(getattr(features, "beat_energy", ()) or ())
    values = [float(e) for t, e in zip(beats, energy) if start - 1e-3 <= float(t) < start + duration]
    if not values and beats and energy:
        nearest = min(range(min(len(beats), len(energy))), key=lambda i: abs(float(beats[i]) - start))
        values = [float(energy[nearest])]
    return sum(values) / len(values) if values else DEFAULT_ENERGY


def plan_look(look: dict | None, features, starts: list[float], durations: list[float],
              seed: str = "") -> list[dict]:
    """Per shot: dissolve_in (s), slowmo factor, leak, punch_in, brightness offset."""
    n = len(starts)
    plan = [{"dissolve_in": 0.0, "slowmo": 1.0, "leak": False, "punch_in": False, "brightness": 0.0}
            for _ in range(n)]
    if not look or n == 0:
        return plan
    hook = float(getattr(features, "hook_at", 0.0) or 0.0)
    absolute = [shot_energy(features, s, d) for s, d in zip(starts, durations)]
    # Reel excerpts sit around the hook, so absolute energy is high almost everywhere;
    # "quiet" and "peak" are therefore relative to this Reel (rank 0 = quietest shot).
    order = sorted(range(n), key=lambda k: (absolute[k], k))
    rank = [0.0] * n
    for pos, k in enumerate(order):
        rank[k] = pos / max(1, n - 1)
    for i in range(n):
        e = min(absolute[i], rank[i])
        dissolve = float(look.get("dissolve") or 0.0)
        if (i > 0 and dissolve > 0 and e < float(look.get("dissolve_below") or 0)
                and abs(starts[i] - hook) > 0.1
                and durations[i] >= 2 * dissolve and durations[i - 1] >= 2 * dissolve):
            plan[i]["dissolve_in"] = dissolve
        if float(look.get("slowmo") or 1.0) > 1.0 and e < float(look.get("slowmo_below") or 0):
            plan[i]["slowmo"] = float(look["slowmo"])
        threshold = look.get("punch_in_above")
        if threshold is not None and rank[i] >= float(threshold) and 0 < i < n - 1:
            plan[i]["punch_in"] = True
        jitter = float(look.get("exposure_jitter") or 0.0)
        if jitter:
            byte = hashlib.sha256(f"{seed}|{i}".encode()).digest()[0]
            plan[i]["brightness"] = round((byte / 255.0 * 2 - 1) * jitter, 4)
        if look.get("light_leaks") and i % 3 == 1:
            plan[i]["leak"] = True
    return plan


def probe_fps(path: Path) -> float:
    """Source frame rate (0.0 if unknown); ffprobe when present, else FFmpeg's stream line."""
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=avg_frame_rate,r_frame_rate", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30)
        for token in p.stdout.replace("\n", ",").split(","):
            if "/" in token:
                num, den = token.split("/", 1)
                if float(den or 0) > 0 and float(num) > 0:
                    return float(num) / float(den)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=30)
        match = re.search(r"(\d+(?:\.\d+)?) fps", p.stderr)
        return float(match.group(1)) if match else 0.0
    except (OSError, subprocess.SubprocessError):
        return 0.0


def slowmo_factor(wanted: float, src_fps: float, fps: int) -> float:
    """Slow down only as far as the source's extra frames allow (no duplicated frames)."""
    if wanted <= 1.0 or src_fps < 29:
        return 1.0
    return round(min(wanted, src_fps / fps), 3)


def make_light_leak(width: int, height: int, dest: Path) -> Path | None:
    """Warm amber/rose glow from the upper corner, alpha ≤ ~0.4 (Pillow; None if missing)."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    w, h = max(2, width // 4), max(2, height // 4)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w * 0.92) / (w * 0.9)) ** 2 + ((yy - h * 0.08) / (h * 0.55)) ** 2)
    alpha = np.clip(1.0 - d, 0, 1) ** 1.6 * 0.42
    mix = np.clip(yy / h * 1.6, 0, 1)[..., None]
    amber, rose = np.array([255, 170, 80], np.float32), np.array([255, 110, 120], np.float32)
    rgb = amber * (1 - mix) + rose * mix
    rgba = np.dstack([rgb, alpha[..., None] * 255]).astype(np.uint8)
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").resize((width, height), Image.BICUBIC).save(dest)
    return dest


def join_graph(durations: list[float], dissolves: list[float]) -> tuple[str, str]:
    """filter_complex joining N parts: xfade where dissolves[i] > 0 (into part i), else concat.

    Part i is expected to be durations[i] + dissolves[i+1] long. Returns (graph, out label).
    """
    n = len(durations)
    lines = [f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps=24,settb=1/24,format=yuv420p[p{i}]" for i in range(n)]
    cur, pos = "p0", float(durations[0])
    for i in range(1, n):
        out = f"j{i}"
        if dissolves[i] > 0:
            lines.append(f"[{cur}][p{i}]xfade=transition=fade:duration={dissolves[i]:.3f}:offset={pos:.3f}[{out}]")
        else:
            lines.append(f"[{cur}][p{i}]concat=n=2:v=1:a=0,settb=1/24[{out}]")  # same timebase for a later xfade
        cur, pos = out, pos + float(durations[i])
    lines.append(f"[{cur}]format=yuv420p[joined]")  # xfade may hand out 4:4:4
    return ";".join(lines), "joined"
