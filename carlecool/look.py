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
    plan = [{"dissolve_in": 0.0, "slowmo": 1.0, "leak": False, "punch_in": False, "brightness": 0.0,
             "bw": False} for _ in range(n)]
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
    # Black-and-white moments (Lana references): the quietest interior shots, cut in and
    # out hard (a dissolve between colour and B/W looks like a mistake).
    bw = int(look.get("bw_shots") or 0)
    if look.get("bw_share"):
        bw = max(1, round(float(look["bw_share"]) * n))
    if bw and n > 4:
        # 25 Nov (homogeneous look): one contiguous B/W passage in the calmest stretch
        # instead of single B/W shots scattered through the Reel.
        bw = min(bw, n - 2)
        start = min(range(1, n - bw), key=lambda s: (sum(rank[k] for k in range(s, s + bw)), s))
        for i in range(start, start + bw):
            plan[i].update(bw=True, leak=False, slowmo=1.0, dissolve_in=0.0,
                           bw_contrast=float(look.get("bw_contrast") or 1.08))
            if i + 1 < n:
                plan[i + 1]["dissolve_in"] = 0.0
    # The bookends form the loop seam (see seal_loop): keep them untouched, real-time.
    for i in {0, n - 1}:
        plan[i].update(slowmo=1.0, leak=False, punch_in=False, brightness=0.0)
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
    lines = [f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps=24,settb=1/24,setsar=1,format=yuv420p[p{i}]" for i in range(n)]
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


def motion_score(path: Path, *, seconds: float = 8.0, size: tuple[int, int] = (48, 84)) -> float:
    """Mean absolute frame difference (0–255) of a tiny greyscale preview; −1 if unknown."""
    import numpy as np
    w, h = size
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-t", f"{seconds:.1f}", "-i", str(path), "-vf",
                            f"fps=6,scale={w}:{h},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return -1.0
    count = len(p.stdout) // (w * h)
    if count < 3:
        return -1.0
    frames = np.frombuffer(p.stdout[:count * w * h], dtype=np.uint8).reshape(count, h, w).astype(np.float32)
    return float(np.mean(np.abs(np.diff(frames, axis=0))))


def match_motion(shots, energies: list[float], motion: list[float], source_durations: list[float],
                 locked: set[int]):
    """Give the loudest passages the most moving clips and the quiet ones the calm clips.

    Only re-pairs sources among the unlocked interior shots (bookends and signature shots
    stay); never puts the same source in two adjacent shots; offsets are re-derived so
    each source still advances through its footage.
    """
    from .cinematic import Shot
    free = [i for i in range(len(shots)) if i not in locked]
    if len(free) < 2 or any(m < 0 for m in (motion[shots[i].source_index] for i in free)):
        return list(shots)
    pool = sorted((shots[i].source_index for i in free), key=lambda src: -motion[src])
    order = sorted(free, key=lambda i: -energies[i])
    assigned: dict[int, int] = {}
    for i in order:
        neighbours = {shots[j].source_index for j in (i - 1, i + 1) if j in locked and 0 <= j < len(shots)}
        neighbours |= {assigned[j] for j in (i - 1, i + 1) if j in assigned}
        pick = next((k for k, src in enumerate(pool) if src not in neighbours), 0)
        assigned[i] = pool.pop(pick)
    out = list(shots)
    used: dict[int, float] = {}
    for i in range(len(out)):
        src = assigned.get(i, out[i].source_index)
        length = out[i].duration
        if i in assigned:
            room = max(0.0, source_durations[src] - length)
            offset = used.get(src, 0.0)
            offset = offset if offset <= room else 0.0
            out[i] = Shot(src, round(offset, 3), length)
        used[src] = out[i].source_offset + max(0.5, length)
    return out


def frame_exact(shots, total_frames: int, fps: int):
    """Shot durations as whole frames that add up EXACTLY to the Reel length.

    Rounding each shot separately lost up to a few frames (video 95 ms shorter than the
    audio in a 31.6 s test), which shows as a freeze at the loop point.
    """
    from .cinematic import Shot
    edges, t = [0], 0.0
    for shot in shots[:-1]:
        t += shot.duration
        edges.append(min(total_frames - (len(shots) - len(edges)), max(edges[-1] + 1, round(t * fps))))
    edges.append(total_frames)
    return [Shot(s.source_index, s.source_offset, (b - a) / fps) for s, a, b in zip(shots, edges, edges[1:])]


def seal_loop(shots, source_durations: list[float]):
    """Last shot = the footage directly BEFORE the first shot (same clip).

    When TikTok/Instagram jump from the end back to 0:00 the motion simply continues:
    no visible cut at the loop point. Returns (shots, sealed).
    """
    from .cinematic import Shot
    if len(shots) < 3:
        return list(shots), False
    first, last = shots[0], shots[-1]
    # The storyboard may have moved the closing shot to another clip (bookend clip used
    # up); the loop needs the opening clip there, unless it would sit next to itself.
    if first.source_index != last.source_index and shots[-2].source_index == first.source_index:
        return list(shots), False
    dur = source_durations[first.source_index]
    if dur < first.duration + last.duration + 0.05:
        return list(shots), False
    start = min(max(first.source_offset, last.duration), dur - first.duration)
    out = list(shots)
    out[0] = Shot(first.source_index, round(start, 4), first.duration)
    out[-1] = Shot(first.source_index, round(start - last.duration, 4), last.duration)
    return out, True


def strongest_opening(pool: list[int], motion: list[float], dims: list[tuple[int, int]],
                      durations: list[float], *, min_seconds: float = 6.0,
                      style_fit: dict[int, float] | None = None) -> int | None:
    """Opening clip: lively, sharp, well matched to the cover — and long enough to also
    close the loop (seal_loop takes the footage just before the opening shot).

    `pool` is in cover-ranking order (best match first). With style-gate scores:
    40 % style fit + 30 % motion + 15 % cover + 15 % sharpness (a lively clip that misses
    the style, like "Street in Mexico City", must not open). Without: 45/35/20 as before.
    """
    usable = [i for i in pool if durations[i] >= min_seconds] or list(pool)
    if not usable:
        return None
    if style_fit and all(i in style_fit for i in usable) and len(usable) > 2:
        # Reel #46 opened on a modern "Speedboat": lively and sharp, but far from the owner's
        # references. Only the best-fitting third (at least 2) may open the Reel.
        keep = max(2, len(usable) // 3)
        best = set(sorted(usable, key=lambda i: style_fit[i], reverse=True)[:keep])
        usable = [i for i in usable if i in best]
    if len(usable) == 1:
        return usable[0]

    def ranks(values: list[float]) -> dict[int, float]:
        order = sorted(range(len(usable)), key=lambda k: values[k])
        return {usable[k]: pos / (len(usable) - 1) for pos, k in enumerate(order)}

    move = ranks([max(0.0, motion[i]) for i in usable])
    cover = {i: 1 - pos / (len(usable) - 1) for pos, i in enumerate(usable)}
    sharp = ranks([float(min(dims[i][0], dims[i][1] * 9 / 16) if dims[i][0] > dims[i][1] else dims[i][0])
                   for i in usable])
    if style_fit and all(i in style_fit for i in usable):
        fit = ranks([style_fit[i] for i in usable])
        return max(usable, key=lambda i: (0.4 * fit[i] + 0.3 * move[i] + 0.15 * cover[i] + 0.15 * sharp[i],
                                          -usable.index(i)))
    return max(usable, key=lambda i: (0.45 * move[i] + 0.35 * cover[i] + 0.2 * sharp[i], -usable.index(i)))
