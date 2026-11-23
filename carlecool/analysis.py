"""Music analysis for beat-accurate, hook-first Reels.

Primary path: librosa beat tracking at 22.05 kHz, a bass-onset downbeat estimate,
per-beat energy and a bar-aligned 8–15 s excerpt whose hook arrives early.
Fallback path (librosa missing or tracking fails): the original numpy heuristic.
All results are estimates, not labelled musical ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import subprocess

import numpy as np

from .music_structure import detect_structure

MIN_REEL = 15.0  # owner 23 Nov: Reels between 15 and 30 s
MAX_REEL = 30.0
TARGET_REEL = 30.0  # ~30 s Reels in whole musical phrases


@dataclass(frozen=True)
class AudioFeatures:
    bpm: float
    energy: float
    excerpt_start: float
    mood: str
    seconds: float
    beat_phase: float = 0.0  # seconds to first estimated beat relative to excerpt
    structure_events: tuple[float, ...] = ()  # excerpt-relative energy transition candidates
    # Beat-level timeline (excerpt-relative seconds); empty for the legacy path.
    beats: tuple[float, ...] = ()
    downbeats: tuple[float, ...] = ()
    beat_energy: tuple[float, ...] = ()  # 0..1 per beat, same length as beats
    reel_length: float = 0.0  # bar-aligned excerpt length; 0 = caller decides
    hook_at: float = 0.0  # excerpt-relative time of the strongest energy lift
    analyzer: str = "heuristic"
    kicks: tuple[float, ...] = ()  # excerpt-relative audible onsets (cut snapping)
    # Sound character of the excerpt (style choice): spectral centroid in Hz (dark/warm vs
    # bright), share of percussive energy (HPSS) and loud/quiet ratio (space, dynamics).
    timbre_hz: float = 0.0
    percussive: float = 0.0
    dynamics: float = 0.0


def _decode(path: str, rate: int) -> np.ndarray:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)


def _mood(genre: str, energy: float, bpm: float) -> str:
    genre_lower = genre.lower()
    if any(x in genre_lower for x in ("ambient", "chill", "downtempo", "lofi")) or energy < 0.12:
        return "calm"
    if any(x in genre_lower for x in ("house", "techno", "electronic", "dance", "trance")) or bpm >= 115:
        return "nightdrive"
    return "cinematic"


def _norm(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return values
    lo, hi = np.percentile(values, 5), np.percentile(values, 95)
    if not math.isfinite(hi - lo) or hi - lo < 1e-9:
        return np.full(values.shape, 0.5)
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def choose_reel_length(bpm: float, *, target: float = TARGET_REEL, minimum: float | None = None,
                       maximum: float | None = None) -> tuple[float, int]:
    """Whole-bar (4/4) length closest to `target`, preferring whole 4-bar phrases.

    Whole phrases make the end land on the "one" of the next phrase, so when TikTok /
    Instagram repeat the video the music continues seamlessly into the start.
    Window: target −10 s … +4 s, clamped to 15–30 s (20–30 s for the default 30 s, so a
    whole 4-bar phrase always fits).
    """
    minimum = max(MIN_REEL, target - 10.0) if minimum is None else minimum
    maximum = min(MAX_REEL, target + 4.0) if maximum is None else maximum
    bar = 4 * 60.0 / max(60.0, min(200.0, bpm))
    options = [n for n in range(1, 64) if minimum - 1e-6 <= n * bar <= maximum + 1e-6]
    if not options:
        # Extremely slow tempo: one bar is longer than the window; use the window.
        return float(maximum), 0
    phrases = [n for n in options if n % 4 == 0] or [n for n in options if n % 2 == 0] or options
    bars = min(phrases, key=lambda n: (abs(n * bar - target), -n))
    return round(bars * bar, 3), bars


def _downbeat_offset(beat_frames: np.ndarray, bass_onset: np.ndarray) -> int:
    """Pick which of the four beat phases carries the strongest low-frequency onsets."""
    if len(beat_frames) < 8:
        return 0
    idx = np.clip(beat_frames, 0, len(bass_onset) - 1)
    strength = bass_onset[idx]
    scores = [float(np.mean(strength[k::4])) for k in range(4)]
    return int(np.argmax(scores))


def _hook_start(beat_times: np.ndarray, downbeat_idx: list[int], beat_energy: np.ndarray,
                length: float, track_seconds: float, *, lead_bars: int = 1) -> tuple[float, float]:
    """Return (start, hook_time) in song seconds.

    The hook is the downbeat with the biggest energy lift (next 2 bars vs previous 2 bars,
    weighted by absolute loudness). The excerpt starts `lead_bars` before it, so the lift
    lands within the first ~1–3 s — the moment that decides whether viewers keep watching.
    """
    best = None
    for pos, beat_index in enumerate(downbeat_idx):
        start_index = downbeat_idx[pos - lead_bars] if pos >= lead_bars else None
        if start_index is None:
            continue
        start = float(beat_times[start_index])
        if start + length > track_seconds - 0.25:
            break
        before = beat_energy[max(0, beat_index - 8):beat_index]
        after = beat_energy[beat_index:beat_index + 8]
        if len(before) < 4 or len(after) < 4:
            continue
        window = beat_energy[(beat_times >= start) & (beat_times < start + length)]
        lift = float(np.mean(after) - np.mean(before))
        score = 0.6 * lift + 0.4 * float(np.mean(window)) if window.size else lift
        if best is None or score > best[0]:
            best = (score, start, float(beat_times[beat_index]))
    if best is None:
        # No lift found: loudest whole-length window starting on a downbeat.
        candidates = [float(beat_times[i]) for i in downbeat_idx
                      if beat_times[i] + length <= track_seconds - 0.25] or [0.0]
        def loudness(s):
            sel = beat_energy[(beat_times >= s) & (beat_times < s + length)]
            return float(np.mean(sel)) if sel.size else 0.0
        start = max(candidates, key=loudness)
        return start, start
    return best[1], best[2]


def _sound_character(clip: np.ndarray, sr: int) -> tuple[float, float, float]:
    """(spectral centroid Hz, percussive energy share, 90/10 % loudness ratio); zeros on failure."""
    try:
        import librosa
        if clip.size < sr:
            return 0.0, 0.0, 0.0
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=clip, sr=sr)))
        harmonic, percussive = librosa.effects.hpss(clip)
        perc = float(np.sum(percussive ** 2) / (np.sum(harmonic ** 2) + np.sum(percussive ** 2) + 1e-9))
        rms = librosa.feature.rms(y=clip)[0]
        dyn = float(np.percentile(rms, 90) / (np.percentile(rms, 10) + 1e-6))
        return round(centroid, 1), round(perc, 3), round(min(dyn, 99.0), 2)
    except Exception:
        return 0.0, 0.0, 0.0


def _librosa_features(y22: np.ndarray, sr: int, max_seconds: float, genre: str,
                      fixed_start: float | None) -> AudioFeatures:
    import librosa

    track_seconds = len(y22) / sr
    hop = 512
    onset_env = librosa.onset.onset_strength(y=y22, sr=sr, hop_length=hop, aggregate=np.median)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=hop,
                                                 start_bpm=120, tightness=100, trim=False)
    bpm = float(np.atleast_1d(tempo)[0])
    if len(beat_frames) < 16 or not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("Too few beats for confident tracking")
    # Fold implausible octave errors into a typical Reel range.
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    # Kick/bass onsets (<150 Hz) mark the "one" in most electronic and pop music.
    mel = librosa.feature.melspectrogram(y=y22, sr=sr, hop_length=hop, n_mels=64, fmax=8000)
    low_bands = librosa.mel_frequencies(n_mels=64, fmax=8000) < 150
    bass = librosa.power_to_db(mel[low_bands].sum(axis=0, keepdims=True), ref=np.max)[0]
    bass_onset = np.maximum(0.0, np.diff(bass, prepend=bass[0]))
    offset = _downbeat_offset(beat_frames, bass_onset)
    downbeat_idx = list(range(offset, len(beat_frames), 4))
    rms = librosa.feature.rms(y=y22, hop_length=hop)[0]
    per_beat = np.array([float(np.mean(rms[a:b])) if b > a else float(rms[min(a, len(rms) - 1)])
                         for a, b in zip(beat_frames, list(beat_frames[1:]) + [len(rms)])])
    beat_energy = _norm(per_beat)
    length, _bars = choose_reel_length(bpm, target=max_seconds)
    if length > track_seconds - 1.0:
        # Short track: the longest whole-phrase length that still fits.
        length, _bars = choose_reel_length(bpm, target=track_seconds - 2.0, minimum=MIN_REEL,
                                           maximum=max(MIN_REEL, track_seconds - 1.0))
        if length > track_seconds:
            raise ValueError(f"Track shorter than {length}s")
    if fixed_start is not None:
        # "Beginning" mode: first downbeat at/after the requested start.
        later = [float(beat_times[i]) for i in downbeat_idx if beat_times[i] >= fixed_start]
        start = later[0] if later and later[0] + length <= track_seconds else 0.0
        hook = start
    else:
        start, hook = _hook_start(beat_times, downbeat_idx, beat_energy, length, track_seconds)
    end = start + length
    inside = (beat_times >= start - 1e-6) & (beat_times < end - 1e-6)
    rel_beats = tuple(round(float(t - start), 4) for t in beat_times[inside])
    rel_downs = tuple(round(float(beat_times[i] - start), 4) for i in downbeat_idx
                      if start - 1e-6 <= beat_times[i] < end - 1e-6)
    rel_energy = tuple(round(float(e), 4) for e in beat_energy[inside])
    clip = y22[int(start * sr):int(end * sr)]
    energy = float(np.clip(np.mean(np.abs(clip)) * 8, 0, 1)) if clip.size else 0.0
    events = detect_structure(clip, sr)
    # Audible hits (excerpt-relative onsets, same envelope as the beat tracker): cuts snap
    # onto these when the tracked grid drifts a few ms. (A bass-only detector was tried and
    # fired 1–2 frames early on the real songs.)
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=hop, backtrack=False)
    kick_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop)
    kicks = tuple(round(float(t - start), 4) for t in kick_times if start - 0.05 <= t < end)
    timbre_hz, percussive, dynamics = _sound_character(clip, sr)
    return AudioFeatures(
        bpm=round(bpm, 1), energy=round(energy, 3), excerpt_start=round(start, 3),
        mood=_mood(genre, energy, bpm), seconds=round(track_seconds, 3),
        beat_phase=rel_beats[0] if rel_beats else 0.0, structure_events=events,
        beats=rel_beats, downbeats=rel_downs, beat_energy=rel_energy,
        reel_length=length, hook_at=round(max(0.0, hook - start), 3), analyzer="librosa",
        kicks=kicks, timbre_hz=timbre_hz, percussive=percussive, dynamics=dynamics,
    )


def _heuristic_features(y: np.ndarray, reel_seconds: float, genre: str) -> AudioFeatures:
    """Legacy 8 kHz RMS/autocorrelation estimate (used when librosa is unavailable)."""
    rate = 8000
    if len(y) < rate * reel_seconds:
        raise ValueError(f"Track shorter than {reel_seconds}s")
    seconds = len(y) / rate
    window_s = max(1, int(round(reel_seconds)))
    whole = y[:(len(y) // rate) * rate].reshape(-1, rate)
    rms = np.sqrt(np.mean(whole.astype(float) ** 2, axis=1))
    scores = np.convolve(rms, np.ones(window_s) / window_s, mode="valid")
    start = int(np.argmax(scores))
    start = min(start, max(0, int(seconds - reel_seconds)))
    clip = y[start * rate:int((start + reel_seconds) * rate)]
    hop = 200
    frames = clip[:(len(clip) // hop) * hop].reshape(-1, hop)
    env = np.sqrt(np.mean(frames.astype(float) ** 2, axis=1))
    onset = np.maximum(0, np.diff(env, prepend=env[0]))
    onset = onset - onset.mean()
    autocorr = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    fps = rate / hop
    minimum, maximum = int(fps * 60 / 160), int(fps * 60 / 65)
    if autocorr[minimum:maximum + 1].size and autocorr[minimum:maximum + 1].max() > 1e-9:
        best = int(np.argmax(autocorr[minimum:maximum + 1])) + minimum
        bpm = 60 * fps / best
        folded = np.bincount(np.arange(len(onset)) % best,
                             weights=np.maximum(onset, 0.0), minlength=best)
        phase = float(np.argmax(folded) / fps)
    else:
        bpm = 120.0
        phase = 0.0
    energy = float(np.clip(np.mean(np.abs(clip)) * 8, 0, 1))
    events = detect_structure(clip, rate)
    return AudioFeatures(round(float(bpm), 1), round(energy, 3), float(start),
                         _mood(genre, energy, bpm), seconds, round(phase, 3), events,
                         reel_length=float(reel_seconds))


def analyze_audio(path: str, reel_seconds: float, genre: str = "", *,
                  fixed_start: float | None = None) -> AudioFeatures:
    """Analyze a track; `reel_seconds` is the TARGET Reel length (whole phrases around it)."""
    try:
        import librosa  # noqa: F401
    except ImportError:
        librosa = None
    if librosa is not None:
        try:
            y22 = _decode(path, 22050)
            return _librosa_features(y22, 22050, max(MIN_REEL, float(reel_seconds)),
                                     genre, fixed_start)
        except ValueError as exc:
            if "shorter" in str(exc):
                raise
            print("Beat tracking low confidence; heuristic fallback:", type(exc).__name__)
    features = _heuristic_features(_decode(path, 8000), float(reel_seconds), genre)
    if fixed_start is not None:
        from dataclasses import replace
        features = replace(features, excerpt_start=float(fixed_start))
    return features


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
