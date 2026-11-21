"""Near-duplicate filter: different stock IDs that show (almost) the same picture.

Stock sites often have several clips from one shoot ("Cars driving in the rain at night",
"Cars in the city at night"); in a 30 s Reel they read as the same image twice.

Signature per clip: 3 frames (15 / 50 / 85 %) as 64-bit difference hashes, plus an
OpenCLIP image embedding when the model is available. Two clips are duplicates when
their frames are nearly identical (hash distance) or their CLIP embeddings are almost
the same (cosine ≥ CLIP_SAME). No model → hash check only. Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

HASH_SAME = 10      # of 64 bits: same shot / same angle
CLIP_SAME = 0.95    # cosine: same subject, same look


@dataclass
class Signature:
    hashes: list[int]
    embedding: np.ndarray | None = None


def _dhash_at(path: Path, at: float) -> int:
    """64-bit difference hash of the full frame (no letterbox padding, which would make
    every portrait clip look alike)."""
    import subprocess
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=9:8:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                       capture_output=True, timeout=60)
    if len(p.stdout) < 72:
        raise ValueError("No frame")
    g = np.frombuffer(p.stdout[:72], dtype=np.uint8).reshape(8, 9).astype(np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def signature(path: Path, clip=None) -> Signature | None:
    from .render import probe_duration
    try:
        duration = probe_duration(Path(path))
        spots = [max(0.0, duration * f) for f in (0.15, 0.5, 0.85)]
        sig = Signature([_dhash_at(Path(path), t) for t in spots])
    except Exception:
        return None
    if clip is not None:
        try:
            import torch
            from .archives import _remote_frame
            frames = [_remote_frame(str(path), t) for t in spots]
            model, preprocess, _tok = clip
            with torch.no_grad():
                emb = model.encode_image(torch.stack([preprocess(f) for f in frames]))
                emb = torch.nn.functional.normalize(emb, dim=-1).mean(dim=0)
                sig.embedding = torch.nn.functional.normalize(emb, dim=-1).numpy()
        except Exception:
            sig.embedding = None
    return sig


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def same_picture(a: Signature | None, b: Signature | None) -> bool:
    if a is None or b is None:
        return False
    if min(_hamming(x, y) for x in a.hashes for y in b.hashes) <= HASH_SAME:
        return True
    if a.embedding is not None and b.embedding is not None:
        return float(np.dot(a.embedding, b.embedding)) >= CLIP_SAME
    return False


class Library:
    """Signatures of the clips already accepted for this Reel."""

    def __init__(self):
        self.clip = None
        try:
            from .semantic import load_clip, semantic_enabled
            self.clip = load_clip() if semantic_enabled() else None
        except Exception:
            self.clip = None
        self.items: list[tuple[str, Signature]] = []

    def duplicate_of(self, path: Path) -> tuple[str | None, Signature | None]:
        sig = signature(path, self.clip)
        for name, other in self.items:
            if same_picture(sig, other):
                return name, sig
        return None, sig

    def add(self, name: str, sig: Signature | None) -> None:
        if sig is not None:
            self.items.append((name, sig))
