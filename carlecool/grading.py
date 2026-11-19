"""Cover-matched colour grading: Reinhard colour transfer baked into a 3D LUT.

For every licensed clip we measure its colour statistics (CIE Lab mean/std over a few
frames) and those of the album cover, then write a `.cube` LUT that moves the clip
towards the cover's palette. FFmpeg applies it with `lut3d`. Strength and per-channel
ratios are bounded so a loud graphic cover cannot destroy the footage.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

import numpy as np

LUT_SIZE = 17
STRENGTH = 0.65
_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_M_INV = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def _to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = _to_linear(np.clip(rgb, 0, 1)) @ _M.T / _WHITE
    eps = 216 / 24389
    f = np.where(xyz > eps, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    eps = 216 / 24389
    def inv(f):
        return np.where(f ** 3 > eps, f ** 3, (116 * f - 16) / (24389 / 27))
    xyz = np.stack([inv(fx), inv(fy), inv(fz)], axis=-1) * _WHITE
    return _to_srgb(xyz @ _M_INV.T)


def _frames(path: Path, *, video: bool, samples=(0.5, 1.5, 3.0)) -> np.ndarray:
    pixels = []
    for second in (samples if video else (0.0,)):
        cmd = ["ffmpeg", "-v", "error"]
        if video and second > 0:
            cmd += ["-ss", str(second)]
        cmd += ["-i", str(path), "-frames:v", "1", "-vf", "scale=64:64",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0 and len(proc.stdout) == 64 * 64 * 3:
            pixels.append(np.frombuffer(proc.stdout, dtype=np.uint8).reshape(-1, 3))
    if not pixels:
        raise ValueError("No frames decoded for colour statistics")
    return np.concatenate(pixels).astype(np.float64) / 255.0


def lab_stats(path: Path, *, video: bool) -> tuple[np.ndarray, np.ndarray]:
    lab = rgb_to_lab(_frames(path, video=video))
    return lab.mean(axis=0), lab.std(axis=0) + 1e-6


def transfer_lut(src_stats, ref_stats, *, strength: float = STRENGTH,
                 size: int = LUT_SIZE) -> np.ndarray:
    """Return a (size³, 3) RGB table in .cube order (red fastest)."""
    (src_mean, src_std), (ref_mean, ref_std) = src_stats, ref_stats
    ratio = np.clip(ref_std / src_std, [0.75, 0.6, 0.6], [1.3, 1.5, 1.5])
    target_mean = ref_mean.copy()
    # Keep exposure close to the footage: only nudge lightness, mostly move colour.
    target_mean[0] = src_mean[0] + np.clip(ref_mean[0] - src_mean[0], -12, 12)
    target_mean[1:] = src_mean[1:] + np.clip(ref_mean[1:] - src_mean[1:], -18, 18)
    axis = np.linspace(0.0, 1.0, size)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], axis=-1).reshape(-1, 3)
    lab = rgb_to_lab(grid)
    moved = (lab - src_mean) * ratio + target_mean
    out = lab_to_rgb(lab + strength * (moved - lab))
    return np.clip(out, 0.0, 1.0)


def write_cube(table: np.ndarray, path: Path, *, size: int = LUT_SIZE) -> Path:
    lines = ["TITLE \"CarleCool cover match\"", f"LUT_3D_SIZE {size}",
             "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in table]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def cover_luts(cover: Path | None, videos: list[Path], work: Path,
               *, strength: float = STRENGTH) -> list[Path | None]:
    """One LUT per clip (None where statistics are unavailable)."""
    if cover is None or not Path(cover).is_file() or strength <= 0:
        return [None] * len(videos)
    try:
        ref = lab_stats(Path(cover), video=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        return [None] * len(videos)
    luts: list[Path | None] = []
    for index, video in enumerate(videos):
        try:
            table = transfer_lut(lab_stats(video, video=True), ref, strength=strength)
            luts.append(write_cube(table, work / f"cover_match_{index:02d}.cube"))
        except (OSError, ValueError, subprocess.SubprocessError):
            luts.append(None)
    return luts
