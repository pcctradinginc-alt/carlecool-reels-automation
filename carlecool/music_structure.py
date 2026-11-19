"""Free, deterministic musical structure signals from decoded mono PCM.

Events are amplitude-novelty proxies, not claims of genre, true downbeat,
semantic chorus or professionally labelled drops.
"""
from __future__ import annotations
import numpy as np


def detect_structure(samples: np.ndarray, sample_rate: int, *, max_events=12) -> tuple[float, ...]:
    """Find candidate transitions at roughly half-second resolution.

    Local energy and positive-change peaks are combined to find transitions;
    no external API or optional scientific dependencies required.
    """
    if sample_rate < 100 or len(samples) < sample_rate * 3:
        return ()
    hop = max(1, int(sample_rate * .5))
    count = len(samples) // hop
    rms = np.sqrt(np.mean(np.asarray(samples[:count * hop], dtype=np.float64)
                          .reshape(count, hop) ** 2, axis=1))
    if not np.isfinite(rms).all() or float(rms.max()) < 1e-5:
        return ()
    # Smooth to avoid overreacting to isolated percussive transients.
    smooth = np.convolve(rms, np.ones(3) / 3, mode="same")
    novelty = np.abs(np.diff(smooth, prepend=smooth[0]))
    typical = np.median(novelty)
    threshold = max(float(np.quantile(novelty, .83)), typical * 2.5, 1e-6)
    candidates = np.flatnonzero(novelty > threshold)
    candidates = [int(i) for i in candidates if 2 <= i < count - 2
                  and novelty[i] >= novelty[i - 1] and novelty[i] >= novelty[i + 1]]
    # Prefer largest changes subject to a 2 s minimum separation.
    chosen = []
    for index in sorted(candidates, key=lambda i: (-novelty[i], i)):
        t = index * hop / sample_rate
        if all(abs(t - existing) >= 2.0 for existing in chosen):
            chosen.append(round(float(t), 3))
        if len(chosen) >= max_events:
            break
    return tuple(sorted(chosen))


def align_to_structure(cut_lengths: list[float], events: tuple[float, ...],
                       *, tolerance=0.65, min_shot=1.25) -> list[float]:
    """Snap planned boundaries to nearby transition candidates if safe."""
    if len(cut_lengths) < 2 or not events:
        return cut_lengths
    duration = sum(cut_lengths)
    original = np.cumsum(cut_lengths[:-1])
    boundaries = [0.0]
    for point in original:
        close = [e for e in events if abs(e - float(point)) <= tolerance
                 and e - boundaries[-1] >= min_shot
                 and duration - e >= min_shot]
        value = min(close, key=lambda e: abs(e - float(point))) if close else float(point)
        if value - boundaries[-1] < min_shot:
            value = float(point)
        boundaries.append(value)
    boundaries.append(duration)
    lengths = [round(max(0, boundaries[i+1] - boundaries[i]), 3)
               for i in range(len(boundaries) - 1)]
    lengths[-1] = round(duration - sum(lengths[:-1]), 3)
    if any(l < 1.0 for l in lengths):
        return cut_lengths
    return lengths
