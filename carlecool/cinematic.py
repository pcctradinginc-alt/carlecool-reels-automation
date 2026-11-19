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


def build_storyboard(durations: list[float], source_durations: list[float],
                     *, seed: str = "") -> list[Shot]:
    """Rotate sources without repeatedly restarting every video at time zero.

    Distinct clips are preferred over immediate repeats. Each reused clip
    advances through its own footage. No uploads, inference, or network access.
    """
    if not durations or not source_durations:
        raise ValueError("At least one shot and source required")
    if any(not math.isfinite(x) or x <= 0 for x in durations + source_durations):
        raise ValueError("Durations must be positive and finite")
    offsets = [0.0] * len(source_durations)
    shots = []
    last = -1
    for index, length in enumerate(durations):
        # Stable variation for a song/edition without scrambling source lanes.
        shift = int.from_bytes(hashlib.sha256(f"{seed}:{index}".encode()).digest()[:2], "big")
        preferred = (index + shift % len(source_durations)) % len(source_durations)
        if len(source_durations) > 1 and preferred == last:
            preferred = (preferred + 1) % len(source_durations)
        source_duration = source_durations[preferred]
        room = max(0.0, source_duration - min(length, source_duration))
        offset = min(offsets[preferred], room)
        shots.append(Shot(preferred, round(offset, 3), length))
        offsets[preferred] = (offset + max(0.5, length)) % max(source_duration, 0.5)
        last = preferred
    return shots
