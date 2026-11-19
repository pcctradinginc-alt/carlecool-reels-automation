"""Content-aware 9:16 reframing of landscape footage.

A centre crop of 16:9 keeps only the middle ~32 % of the picture, so the subject
(skater, turntable, palm) is often cut away. Instead, for every shot we look at the
frames it actually uses and place the 9:16 window where the picture is most
interesting:

    interest(column) = 0.75 · motion (spread to subject width) + 0.25 · detail, × centre prior

* motion  = absolute difference between consecutive sampled frames (moving subjects)
* detail  = gradient magnitude (texture, edges, objects), so static shots still work

If the best window moves during a shot, the crop pans smoothly (eased, speed-limited)
instead of jumping. Pure numpy + FFmpeg, no model; portrait footage is left untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import subprocess

import numpy as np

SAMPLE_FPS = 3.0
SAMPLE_WIDTH = 192
TARGET_ASPECT = 9 / 16
MAX_PAN_PER_SECOND = 0.18  # fraction of the source width
MIN_PAN = 0.035            # smaller moves stay static (no wobble)


@dataclass(frozen=True)
class Crop:
    width: int     # crop width in source pixels (height = full source height)
    x_start: int   # left edge at the start of the shot
    x_end: int     # left edge at the end of the shot


class FrameSamples:
    """Low-resolution greyscale frames of one source clip, decoded once."""

    def __init__(self, frames: np.ndarray, times: np.ndarray, src_w: int, src_h: int):
        self.frames, self.times, self.src_w, self.src_h = frames, times, src_w, src_h

    @classmethod
    def decode(cls, path: Path, src_w: int, src_h: int) -> "FrameSamples":
        h = max(2, int(round(SAMPLE_WIDTH * src_h / src_w / 2)) * 2)
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
             f"fps={SAMPLE_FPS},scale={SAMPLE_WIDTH}:{h},format=gray",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True, timeout=120)
        size = SAMPLE_WIDTH * h
        count = len(proc.stdout) // size
        if count < 1:
            raise ValueError("No frames decoded for reframing")
        frames = np.frombuffer(proc.stdout[:count * size], dtype=np.uint8)
        frames = frames.reshape(count, h, SAMPLE_WIDTH).astype(np.float32) / 255.0
        times = (np.arange(count) + 0.5) / SAMPLE_FPS
        return cls(frames, times, src_w, src_h)


def needs_reframe(src_w: int, src_h: int) -> bool:
    """Only clearly wider-than-9:16 footage is reframed."""
    return src_w > 0 and src_h > 0 and src_w / src_h > TARGET_ASPECT * 1.15


def _column_interest(frames: np.ndarray) -> np.ndarray:
    """Interest per column for a stack of frames (n, h, w) → (n, w)."""
    gx = np.abs(np.diff(frames, axis=2, prepend=frames[:, :, :1]))
    gy = np.abs(np.diff(frames, axis=1, prepend=frames[:, :1, :]))
    detail = (gx + gy).mean(axis=1)
    if len(frames) > 1:
        motion = np.abs(np.diff(frames, axis=0)).mean(axis=1)
        motion = np.vstack([motion[:1], motion])
    else:
        motion = np.zeros_like(detail)

    def norm(a):
        peak = np.percentile(a, 99) if a.size else 0.0
        return a / peak if peak > 1e-6 else np.zeros_like(a)

    has_motion = float(motion.max()) > 1e-3
    if has_motion:
        # Spread motion over roughly a subject's width: a moving person/board only
        # changes pixels at its edges, while a patterned wall is "detailed" everywhere.
        span = max(3, motion.shape[1] // 8)
        kernel = np.ones(span) / span
        motion = np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="same"), 1, motion)
        score = 0.75 * norm(motion) + 0.25 * norm(detail)
    else:
        score = norm(detail)
    w = score.shape[1]
    centre = np.exp(-0.5 * ((np.arange(w) - (w - 1) / 2) / (0.38 * w)) ** 2)
    return score * (0.8 + 0.2 * centre)


def _best_left(profile: np.ndarray, window: int) -> int:
    """Left edge (sample columns) of the window with the highest total interest."""
    w = len(profile)
    if window >= w:
        return 0
    smooth = np.convolve(profile, np.ones(5) / 5, mode="same")
    sums = np.convolve(smooth, np.ones(window), mode="valid")
    best = float(sums.max())
    # Prefer the most central of near-equal windows (stability on flat images).
    candidates = np.flatnonzero(sums >= best * 0.985)
    centre = (w - window) / 2
    return int(candidates[np.argmin(np.abs(candidates - centre))])


def plan_crop(samples: FrameSamples, start: float, duration: float) -> Crop:
    """Crop window for the source time range [start, start + duration]."""
    crop_w = int(round(samples.src_h * TARGET_ASPECT / 2)) * 2
    crop_w = min(crop_w, samples.src_w - samples.src_w % 2)
    max_left = samples.src_w - crop_w
    scale = samples.src_w / SAMPLE_WIDTH
    window = max(1, int(round(crop_w / scale)))
    end = start + max(duration, 1e-3)
    idx = np.flatnonzero((samples.times >= start - 0.2) & (samples.times <= end + 0.2))
    if idx.size == 0:
        idx = np.array([int(np.argmin(np.abs(samples.times - start)))])
    frames = samples.frames[max(0, idx[0] - 1):idx[-1] + 1]
    interest = _column_interest(frames)[-len(idx):]
    half = max(1, len(idx) // 2)
    first = _best_left(interest[:half].mean(axis=0), window)
    last = _best_left(interest[-half:].mean(axis=0), window)
    overall = _best_left(interest.mean(axis=0), window)

    def to_src(left):
        return int(min(max_left, max(0, round(left * scale))))

    x0, x1, xm = to_src(first), to_src(last), to_src(overall)
    if abs(x1 - x0) < MIN_PAN * samples.src_w or len(idx) < 3:
        return Crop(crop_w, xm, xm)
    limit = MAX_PAN_PER_SECOND * samples.src_w * max(duration, 0.1)
    if abs(x1 - x0) > limit:
        mid, direction = (x0 + x1) / 2, math.copysign(1.0, x1 - x0)
        x0 = int(round(mid - direction * limit / 2))
        x1 = int(round(mid + direction * limit / 2))
    return Crop(crop_w, int(min(max_left, max(0, x0))), int(min(max_left, max(0, x1))))


def crop_filter(crop: Crop, src_h: int, duration: float) -> str:
    """FFmpeg crop with an eased pan (smoothstep) when the window moves."""
    if crop.x_start == crop.x_end:
        return f"crop={crop.width}:{src_h}:{crop.x_start}:0"
    d = max(duration, 0.1)
    p = f"min(max(t/{d:.3f},0),1)"
    ease = f"({p}*{p}*(3-2*{p}))"
    x = f"{crop.x_start}+({crop.x_end - crop.x_start})*{ease}"
    return f"crop={crop.width}:{src_h}:'{x}':0"
