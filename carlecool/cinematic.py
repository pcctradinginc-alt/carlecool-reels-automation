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


def _beats_for_energy(level: float, pace: str) -> int:
    """Shot length in beats: calm passages breathe, peaks cut fast (viral pacing)."""
    base = 8 if level < 0.35 else 4 if level < 0.7 else 2
    if pace == "slow":
        base *= 2
    elif pace == "fast":
        base = max(1, base // 2)
    return base


def plan_cuts_from_beats(duration: float, beats: tuple[float, ...] | list[float],
                         downbeats: tuple[float, ...] | list[float],
                         beat_energy: tuple[float, ...] | list[float], *,
                         pace: str = "medium", hook_at: float = 0.0,
                         min_shot: float = 0.42) -> list[float]:
    """Energy-driven cut density on tracked beats.

    * Low energy → 8 beats per shot, mid → 4, peaks → 2 (pace halves/doubles this).
    * Long shots (≥4 beats) start on downbeats so phrases and pictures change together.
    * A cut is forced on the hook so the visual change hits with the musical lift.
    * Falls back to `plan_cuts` grid when the beat timeline is unusable.
    """
    if pace not in ("slow", "medium", "fast"):
        raise ValueError("Invalid pace")
    if not 0 < duration <= 600 or not math.isfinite(duration):
        raise ValueError("Invalid video duration")
    beats = [float(b) for b in beats if 0 <= b < duration]
    if len(beats) < 4 or len(beat_energy) < len(beats):
        span = (beats[1] - beats[0]) if len(beats) > 1 else 0.5
        return plan_cuts(duration, 60.0 / max(span, 0.3), pace=pace)
    energy = [float(e) for e in beat_energy[:len(beats)]]
    downs = {round(float(d), 3) for d in downbeats}
    boundaries = [0.0]
    i = 0
    # First cut: on the first downbeat/beat at least `min_shot` in, or on the hook.
    while i < len(beats):
        current = beats[i]
        if current - boundaries[-1] < min_shot:
            i += 1
            continue
        if len(boundaries) > 1 or current > 0:
            boundaries.append(current)
        level = max(energy[i:i + 4]) if energy[i:i + 4] else 0.5
        step = _beats_for_energy(level, pace)
        nxt = i + step
        if step >= 4:
            # Snap long shots to the next downbeat if one is within the shot.
            for j in range(i + 1, min(len(beats), i + step + 1)):
                if round(beats[j], 3) in downs and j - i >= max(2, step // 2):
                    nxt = j
                    break
        # Force a cut exactly at the hook if we would otherwise jump over it.
        if hook_at > boundaries[-1] + min_shot and nxt < len(beats) and beats[nxt] > hook_at + 1e-3:
            hook_idx = min(range(len(beats)), key=lambda k: abs(beats[k] - hook_at))
            if beats[hook_idx] - boundaries[-1] >= min_shot and hook_idx > i:
                nxt = hook_idx
        i = nxt
    if duration - boundaries[-1] < min_shot and len(boundaries) > 1:
        boundaries.pop()
    boundaries = sorted(set(round(b, 4) for b in boundaries if 0 <= b < duration))
    if boundaries[0] != 0.0:
        boundaries.insert(0, 0.0)
    boundaries.append(float(duration))
    out = [round(b - a, 4) for a, b in zip(boundaries, boundaries[1:])]
    out = [x for x in out if x > 0]
    out[-1] = round(duration - sum(out[:-1]), 4)
    return out


def build_storyboard(durations: list[float], source_durations: list[float],
                     *, seed: str = "", no_bookend: set[int] | frozenset[int] = frozenset(),
                     featured_sources: tuple[int, int] | None = None) -> list[Shot]:
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
    featured = {}
    if featured_sources is not None:
        if (len(durations) < 4 or len(featured_sources) != 2
                or len(set(featured_sources)) != 2
                or any(type(x) is not int or not 0 <= x < count for x in featured_sources)):
            raise ValueError("Creative v5 requires two distinct sources and at least four scenes")
        # Two interior shots: first the female subject, then the skater.
        # Preserve intro/outro continuity and the existing music-aligned cuts.
        featured = {1: featured_sources[0], max(2, (len(durations) - 1) // 2): featured_sources[1]}
    bookend = next((i for i in range(count) if i not in no_bookend), 0)
    second = next((i for i in range(count) if i not in no_bookend and i != bookend), None)
    offsets = [0.0] * count
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
        if index in featured:
            preferred = featured[index]
        candidates = [(preferred + k) % count for k in range(count)]

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
        if index in featured and choice != featured[index]:
            raise RuntimeError("Creative v5 featured source cannot fit its music-aligned scene")
        source_duration = source_durations[choice]
        if source_duration - offsets[choice] < length - 1e-6:
            offsets[choice] = 0.0  # rewind rather than loop past the end
        room = max(0.0, source_duration - min(length, source_duration))
        offset = min(offsets[choice], room)
        shots.append(Shot(choice, round(offset, 3), length))
        offsets[choice] = offset + max(0.5, length)
        if offsets[choice] >= source_duration:
            offsets[choice] = 0.0
        last = choice
    return shots
