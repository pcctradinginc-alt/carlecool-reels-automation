"""Optional album-art palette matching with strictly bounded downloads and local FFmpeg.

No pretrained model, paid API, public artifacts or unlicensed footage.
Failures intentionally retain the existing source order.
"""
from __future__ import annotations

import ipaddress
import math
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

import numpy as np
import requests

MAX_ART_BYTES = 8_000_000
PIXELS = 32 * 32 * 3


def _allowed_cover_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    # Only canonical SoundCloud artwork CDN hosts, never arbitrary image URLs.
    return bool(re.fullmatch(r"i[1-4]\.sndcdn\.com", (parsed.hostname or "").lower()))


SIZE_SUFFIX = re.compile(r"-(?:large|t\d+x\d+|original|crop|small|badge|tiny|mini|t67x67|t300x300)(\.(?:jpg|jpeg|png))$", re.I)


def artwork_variants(url: str) -> list[str]:
    """Largest first: the API's default `-large` artwork is only 100x100 px, which made
    the cover on the end card blurry. SoundCloud also serves 3000x3000 / 500x500."""
    match = SIZE_SUFFIX.search(url or "")
    if not match:
        return [url] if url else []
    stem, ext = url[:match.start()], match.group(1)
    out = []
    for size in ("t3000x3000", "original", "t500x500"):
        candidate = f"{stem}-{size}{ext}"
        if candidate not in out:
            out.append(candidate)
    if url not in out:
        out.append(url)
    return out


def fetch_cover(url: str, destination: Path, *, session=None) -> bool:
    """Download the largest available public artwork; never follow cross-domain redirects."""
    if not url or not _allowed_cover_url(url):
        return False
    session = session or requests.Session()
    for candidate in artwork_variants(url):
        if _allowed_cover_url(candidate) and _fetch_one(candidate, destination, session):
            return True
    return False


def _fetch_one(url: str, destination: Path, session) -> bool:
    try:
        response = session.get(url, stream=True, allow_redirects=False, timeout=(10, 25))
        try:
            if response.status_code != 200:
                return False
            if int(response.headers.get("Content-Length") or 0) > MAX_ART_BYTES:
                return False
            buffer = bytearray()
            for chunk in response.iter_content(65536):
                buffer.extend(chunk)
                if len(buffer) > MAX_ART_BYTES:
                    return False
            if len(buffer) < 1024:
                return False
        finally:
            response.close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(buffer)
        return True
    except (requests.RequestException, OSError, ValueError):
        return False


def _thumbnail(path: Path, *, video: bool) -> np.ndarray:
    args = ["ffmpeg", "-v", "error"]
    if video:
        args += ["-ss", "0.5"]
    args += ["-i", str(path), "-frames:v", "1", "-vf", "scale=32:32",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True, timeout=30)
    if len(proc.stdout) != PIXELS:
        raise ValueError("Invalid FFmpeg thumbnail dimensions")
    return np.frombuffer(proc.stdout, dtype=np.uint8).reshape(32, 32, 3)


def _fingerprint(rgb: np.ndarray) -> np.ndarray:
    """Robustly compare overall color character, not semantic image contents."""
    pixels = rgb.astype(np.float32).reshape(-1, 3) / 255.0
    means = np.mean(pixels, axis=0)
    brightness = np.mean(pixels, axis=1)
    saturation = np.max(pixels, axis=1) - np.min(pixels, axis=1)
    return np.concatenate([means, [np.median(brightness), np.mean(saturation)]])


def rank_by_cover(cover: Path, paths: list[Path]) -> tuple[list[int], list[float]]:
    """Return conservative palette ranking, preserving source order on failure.

    A weak palette fit can change ordering but never removes a licensed clip.
    Identical colors remain in original discovery order.
    """
    if not paths:
        return [], []
    try:
        art = _fingerprint(_thumbnail(cover, video=False))
    except (OSError, ValueError, subprocess.SubprocessError):
        return list(range(len(paths))), []
    scores = []
    for path in paths:
        try:
            vec = _fingerprint(_thumbnail(path, video=True))
            distance = float(np.linalg.norm((vec - art) * [1, 1, 1, .5, .5]))
            scores.append(round(max(0., 1. - distance / 2.), 4))
        except (OSError, ValueError, subprocess.SubprocessError):
            scores.append(0.)
    ranked = sorted(range(len(paths)), key=lambda i: (-scores[i], i))
    return ranked, scores
