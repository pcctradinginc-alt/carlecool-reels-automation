"""Deterministic music-led storyboard: avoid repeating the first frames of stock clips.

All functions are offline, zero-cost and safe if beat tracking has low confidence.
The timeline is a *visual edit plan*, not a claim of semantic film understanding.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math


@dataclass(frozen=True)
class Shot:
    source_index: int
    source_offset: float
    duration: float


def plan_cuts(duration: float, bpm: float, *, pace: str = "medium",
              beat_phase: float = 0.0) -> list[float]:
    """Plan shot boundaries on estimated beat positions (including phase).

    The first shot can be shorter so subsequent boundaries align with the music.
    Avoid sub-second shots, floating-point drift and zero-duration tails.
    """
    if pace not in ("slow", "medium", "fast"):
        raise ValueError("Invalid pace")
    if not 0 < duration <= 600 or not math.isfinite(duration):
        raise ValueError("Invalid video duration")
    if not math.isfinite(bpm) or bpm <= 0:
        bpm = 120.0
    beat = 60.0 / max(65.0, min(200.0, bpm))
    beats_per_shot = {"slow": 12, "medium": 8, "fast": 4}[pace]
    span = beats_per_shot * beat
    # Phase refers to the beginning of the selected audio excerpt, not the song.
    phase = beat_phase % beat if math.isfinite(beat_phase) else 0.0
    boundaries = [0.0]
    candidate = phase
    while candidate < 1.25:
        candidate += beat
    while candidate < duration - 1.0:
        if candidate - boundaries[-1] >= 1.25:
            boundaries.append(candidate)
        candidate += span
    boundaries.append(float(duration))
    # Fold tiny trailing shots into their predecessor.
    if len(boundaries) > 2 and boundaries[-1] - boundaries[-2] < 1.0:
        boundaries.pop(-2)
    out = [round(b - a, 3) for a, b in zip(boundaries, boundaries[1:])]
    out[-1] = round(duration - sum(out[:-1]), 3)
    return out


FPS = 24


def snap_to_frames(durations: list[float], total: float, *, fps: int = FPS) -> list[float]:
    """Round every cut to a whole frame so per-shot renders add up exactly."""
    frame = 1.0 / fps
    edges, elapsed = [], 0.0
    for d in durations[:-1]:
        elapsed += d
        edges.append(round(elapsed / frame) * frame)
    total_frames = round(total / frame)
    points = [0.0] + edges + [total_frames * frame]
    out = [round(b - a, 4) for a, b in zip(points, points[1:])]
    if any(x < frame for x in out):
        return [round(x, 4) for x in durations]
    return out


def _bars_for_energy(level: float, pace: str) -> float:
    """Shot length in BARS. Cuts follow musical phrases, not individual beats.

    Live feedback ("luère froid", 152 BPM): cutting every 2 beats gave 16 identical
    0.79 s shots — flicker, not editing. Bars keep cuts on the "one".
    """
    if pace == "slow":
        return 1.0 if level >= 0.85 else 2.0
    if pace == "fast":
        return 0.5 if level >= 0.6 else 1.0
    return 1.0 if level >= 0.45 else 2.0


def plan_cuts_from_beats(duration: float, beats: tuple[float, ...] | list[float],
                         downbeats: tuple[float, ...] | list[float],
                         beat_energy: tuple[float, ...] | list[float], *,
                         pace: str = "medium", hook_at: float = 0.0,
                         min_shot: float = 0.9, kicks: tuple[float, ...] | list[float] = ()) -> list[float]:
    """Bar-based, energy-aware cut plan.

    * Cuts land on bar starts (downbeats); a half-bar only in `fast` pace at peaks.
    * Calm bars → 2-bar shots, energetic bars → 1-bar shots (medium pace).
    * A cut is always placed on the hook's downbeat so picture and drop change together.
    * Very fast songs (>140 BPM) are treated in half-time: their bars are short anyway.
    * A cut snaps to the audible hit (onset) when it is within 40 ms of the tracked grid.
    * Each cut is pulled one frame early so the new image registers with the kick.
    Falls back to the beat grid planner when no usable bar grid exists.
    """
    if pace not in ("slow", "medium", "fast"):
        raise ValueError("Invalid pace")
    if not 0 < duration <= 600 or not math.isfinite(duration):
        raise ValueError("Invalid video duration")
    beats = [float(b) for b in beats if 0 <= b < duration]
    if len(beats) < 4:
        return plan_cuts(duration, 120.0, pace=pace)
    period = float(sorted(b2 - b1 for b1, b2 in zip(beats, beats[1:]))[len(beats) // 2 - 1])
    energy = [float(e) for e in list(beat_energy)[:len(beats)]] + [0.5] * max(0, len(beats) - len(beat_energy))
    bars = sorted({round(float(d), 4) for d in downbeats if 0 <= d < duration})
    if len(bars) < 2:
        bars = [beats[i] for i in range(0, len(beats), 4)]
    bar_len = float(sorted(b2 - b1 for b1, b2 in zip(bars, bars[1:]))[(len(bars) - 1) // 2]) if len(bars) > 1 else 4 * period
    if bar_len < 1.7:  # >140 BPM: a 2-bar unit is the musical phrase people feel
        min_shot = max(min_shot, bar_len * 0.95)

    def level_at(t0: float, t1: float) -> float:
        vals = [e for b, e in zip(beats, energy) if t0 - 1e-6 <= b < t1]
        return sum(vals) / len(vals) if vals else 0.5

    bar_grid = sorted(set(bars + [bars[-1] + k * bar_len for k in range(1, 64)
                                   if bars[-1] + k * bar_len < duration]))
    # Slow songs (bar > 2.2 s, i.e. < ~110 BPM): a 2-bar shot would last 5 s+. Use
    # half bars (beats 1 and 3) as the editing unit instead ("NAD+", 96 BPM: 3 shots in
    # 10 s was far too static). Fast songs keep whole bars.
    unit = bar_len / 2 if bar_len > 2.2 else bar_len
    grid = (sorted(set(bar_grid + [g + bar_len / 2 for g in bar_grid if g + bar_len / 2 < duration]))
            if unit < bar_len else bar_grid)
    half = sorted(set(grid + [g + unit / 2 for g in grid if g + unit / 2 < duration]))
    hook = min(grid, key=lambda g: abs(g - hook_at)) if hook_at > 0 else None
    boundaries = [0.0]
    t = grid[0] if grid[0] >= min_shot else next((g for g in grid if g >= min_shot), duration)
    if grid[0] > 1e-3 and grid[0] < min_shot:
        t = grid[0] if grid[0] >= 0.5 else t  # short pickup before the first "one"
    while t < duration - min_shot * 0.6:
        if t - boundaries[-1] >= min(min_shot, 0.5) - 1e-6:
            boundaries.append(t)
        units = _bars_for_energy(level_at(t, t + unit), pace)
        if units * unit > 3.3:
            units = max(1.0, units / 2)  # never longer than ~3 s per shot
        if units < 1 and units * unit < 0.9:
            units = 1.0  # sub-unit cuts only where they stay readable
        step = units * unit
        target = t + step
        pool = half if step < unit else grid
        nxt = min((g for g in pool if g >= target - 1e-3), default=duration)
        if hook is not None and t + 1e-3 < hook < nxt - 1e-3 and hook - t >= min_shot * 0.9:
            nxt = hook  # always change picture on the hook
        if nxt - t < min_shot - 1e-6:
            nxt = min((g for g in grid if g - t >= min_shot - 1e-6), default=duration)
        t = nxt
    frame = 1.0 / FPS
    kick_list = sorted(float(k) for k in kicks if 0 < k < duration)
    if kick_list:
        snapped = [boundaries[0]]
        for b in boundaries[1:]:
            near = min(kick_list, key=lambda k: abs(k - b))
            snapped.append(near if abs(near - b) <= 0.04 else b)
        boundaries = snapped
    edges = [b - frame if b - frame > 0 else b for b in boundaries[1:]]  # one frame early
    points = [0.0] + [e for e in edges if 0 < e < duration] + [float(duration)]
    out = [round(b - a, 4) for a, b in zip(points, points[1:]) if b - a > 1e-6]
    out[-1] = round(duration - sum(out[:-1]), 4)
    if len(out) > 1 and out[-1] < 0.5:
        out[-2] = round(out[-2] + out[-1], 4)
        out.pop()
    return out


def build_storyboard(durations: list[float], source_durations: list[float],
                     *, seed: str = "", no_bookend: set[int] | frozenset[int] = frozenset()) -> list[Shot]:
    """Rotate sources without repeatedly restarting every video at time zero.

    Distinct clips are preferred over immediate repeats. Each reused clip
    advances through its own footage. Sources in `no_bookend` (e.g. a short,
    low-resolution AI shot) never open or close the Reel, and a shot avoids a
    source whose remaining footage would force a visible loop.
    """
    if not durations or not source_durations:
        raise ValueError("At least one shot and source required")
    if any(not math.isfinite(x) or x <= 0 for x in durations + source_durations):
        raise ValueError("Durations must be positive and finite")
    count = len(source_durations)
    bookend = next((i for i in range(count) if i not in no_bookend), 0)
    second = next((i for i in range(count) if i not in no_bookend and i != bookend), None)
    offsets = [0.0] * count
    uses = [0] * count
    shots = []
    last = -1
    for index, length in enumerate(durations):
        shift = int.from_bytes(hashlib.sha256(f"{seed}:{index}".encode()).digest()[:2], "big")
        preferred = (index + shift % count) % count
        # Story arc: open with the best cover-matching clip and return to it at
        # the end, so the last frame flows back into the first (loop).
        if len(durations) >= 3 and count >= 2:
            if index == 0 or index == len(durations) - 1:
                preferred = bookend
            elif index == 1 and second is not None:
                preferred = second
        rotation = [(preferred + k) % count for k in range(count)]
        # Never repeat a clip while another one is still unused: least-used first, the
        # seeded rotation only breaks ties. (The closing shot returns to the opening clip
        # on purpose: it continues that footage into the loop, see look.seal_loop.)
        closing = len(durations) >= 3 and count >= 2 and index == len(durations) - 1
        candidates = rotation if closing else sorted(rotation, key=lambda c: uses[c])

        def fits(src):
            return source_durations[src] - offsets[src] >= length - 1e-6 or offsets[src] == 0 and source_durations[src] >= length - 1e-6

        def allowed(src):
            if src == last and count > 1:
                return False
            if src in no_bookend and (index == 0 or index == len(durations) - 1) and count > 1:
                return False
            return True

        choice = next((c for c in candidates if allowed(c) and fits(c)), None)
        if choice is None:
            choice = next((c for c in candidates if allowed(c) and source_durations[c] >= length - 1e-6), None)
        if choice is None:
            choice = next((c for c in candidates if allowed(c)), preferred)
        source_duration = source_durations[choice]
        if source_duration - offsets[choice] < length - 1e-6:
            offsets[choice] = 0.0  # rewind rather than loop past the end
        room = max(0.0, source_duration - min(length, source_duration))
        offset = min(offsets[choice], room)
        shots.append(Shot(choice, round(offset, 3), length))
        uses[choice] += 1
        offsets[choice] = offset + max(0.5, length)
        if offsets[choice] >= source_duration:
            offsets[choice] = 0.0
        last = choice
    return shots
