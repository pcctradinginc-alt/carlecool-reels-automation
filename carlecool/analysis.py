"""Deterministic beat/energy estimates (heuristics, not AI mood classification)."""
from __future__ import annotations

from dataclasses import dataclass
import subprocess
import numpy as np
from .music_structure import detect_structure


@dataclass(frozen=True)
class AudioFeatures:
    bpm: float
    energy: float
    excerpt_start: float
    mood: str
    seconds: float
    beat_phase: float = 0.0  # seconds to first estimated beat relative to excerpt
    structure_events: tuple[float, ...] = ()  # excerpt-relative energy transition candidates


def analyze_audio(path: str, reel_seconds: int, genre: str = "") -> AudioFeatures:
    """Decode low-resolution PCM via FFmpeg and estimate onset periodicity."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    )
    y = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)
    if len(y) < 8000 * reel_seconds:
        raise ValueError(f"Track shorter than {reel_seconds}s")
    seconds = len(y) / 8000
    # 1-second RMS windows select the loudest consistent 30s segment (avoid clipped tails).
    whole = y[:(len(y) // 8000) * 8000].reshape(-1, 8000)
    rms = np.sqrt(np.mean(whole.astype(float) ** 2, axis=1))
    window = np.ones(reel_seconds) / reel_seconds
    scores = np.convolve(rms, window, mode="valid")
    # Moderate preference for later sections; never near the very last second.
    start = int(np.argmax(scores))
    start = min(start, max(0, int(seconds - reel_seconds)))
    clip = y[start * 8000:(start + reel_seconds) * 8000]
    # Short-time energy onset proxy; autocorrelation across plausible beat lags.
    hop = 200
    frames = clip[:(len(clip) // hop) * hop].reshape(-1, hop)
    env = np.sqrt(np.mean(frames.astype(float) ** 2, axis=1))
    onset = np.maximum(0, np.diff(env, prepend=env[0]))
    onset = onset - onset.mean()
    autocorr = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    fps = 8000 / hop
    minimum, maximum = int(fps * 60 / 160), int(fps * 60 / 65)
    if autocorr[minimum:maximum + 1].size and autocorr[minimum:maximum + 1].max() > 1e-9:
        best = int(np.argmax(autocorr[minimum:maximum + 1])) + minimum
        bpm = 60 * fps / best
        # Phase-align edits to onset peaks rather than an arbitrary t=0.
        folded = np.bincount(np.arange(len(onset)) % best,
                             weights=np.maximum(onset, 0.0), minlength=best)
        phase = float(np.argmax(folded) / fps)
    else:
        bpm = 120.0  # explicit fallback for quiet music
        phase = 0.0
    energy = float(np.clip(np.mean(np.abs(clip)) * 8, 0, 1))
    genre_lower = genre.lower()
    if any(x in genre_lower for x in ("ambient", "chill", "downtempo", "lofi")) or energy < 0.12:
        mood = "calm"
    elif any(x in genre_lower for x in ("house", "techno", "electronic", "dance", "trance")) or bpm >= 115:
        mood = "nightdrive"
    else:
        mood = "cinematic"
    events = detect_structure(clip, 8000)
    return AudioFeatures(round(float(bpm), 1), round(energy, 3), float(start), mood, seconds, round(phase, 3), events)


def beat_cut_lengths(bpm: float, seconds: int) -> list[float]:
    """Align scene boundaries to 8-beat groupings; final segment fills remainder."""
    interval = min(6.0, max(3.0, 8 * 60 / max(65, bpm)))
    output = []
    remaining = float(seconds)
    while remaining > 0.1:
        step = min(interval, remaining)
        if remaining - step < 1.0:
            step = remaining
        output.append(round(step, 3))
        remaining -= step
    return output
