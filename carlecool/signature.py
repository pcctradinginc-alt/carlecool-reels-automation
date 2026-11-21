"""Signature shots ADDED on top of the v4 footage: cover motif, a skater, a woman.

Unlike the reverted Creative v5 (which replaced the v4 lanes with these subjects),
the proven v4 clips stay untouched; each signature clip is one extra interior shot.

* skater: face not visible — queries favour feet/wheels/silhouettes/back views, CLIP
  ranks "seen from behind" over "close-up face", and OpenCV rejects clips with a large
  frontal face.
* woman: candid, natural — CLIP prefers "candid, natural light" over "posed fashion
  model / heavy make-up".
* variety: clips used in the last 30 previews are never reused for these slots.
Every failure (quota, no hits, no model) just leaves the slot empty.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import numpy as np

from .video import Video, _coverr_request, _is_portrait

MEMORY_REELS = 30
SLOT_POSITION = {"motif": 0.22, "skater": 0.45, "woman": 0.7}
PRIORITY = ("skater", "woman", "motif")

SKATER_QUERIES = {
    "lana": ("skateboard sunset", "skater silhouette", "skateboard road"),
    "rubin": ("skateboard feet", "skateboard wheels", "skatepark"),
    "night": ("skateboard night", "skater night", "skateboard street"),
    None: ("skateboard feet", "skater silhouette", "skateboarding"),
}
WOMAN_QUERIES = {
    "lana": ("woman field sunset", "woman hair wind", "woman summer"),
    "rubin": ("woman beach morning", "woman walking nature", "woman window"),
    "night": ("woman city night", "woman neon", "woman night"),
    None: ("woman walking sunset", "woman nature", "woman walking"),
}
PROMPTS = {
    "skater": (
        ("a skateboarder seen from behind, face not visible",
         "close-up of feet on a skateboard rolling on asphalt",
         "silhouette of a skater against the sky"),
        ("a close-up portrait of a person's face",
         "a skateboard lying on the ground without a person",
         "an empty street without people"),
    ),
    "woman": (
        ("a candid natural photo of a woman outdoors in natural light",
         "a woman walking, documentary style, no posing",
         "a woman with hair blowing in the wind"),
        ("a glamorous posed fashion model in a studio",
         "a heavy make-up beauty close-up",
         "a man", "an empty landscape without people"),
    ),
    "motif": None,
}
FACE_MAX_HEIGHT = 0.12  # frontal face taller than 12 % of the frame → skater rejected


def enabled() -> bool:
    return os.getenv("CARLECOOL_SIGNATURE", "true").strip().lower() in ("true", "1", "yes", "on")


def _rotate(queries: tuple[str, ...], key: str) -> list[str]:
    start = int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") % len(queries)
    return list(queries[start:]) + list(queries[:start])


def search_slot(api_key: str, queries, *, exclude: set[str], session=None,
                per_query: int = 30, enough: int = 4, role: str = "") -> list[Video]:
    """Up to 3 Coverr requests; stops once `enough` usable clips were found."""
    import requests
    session = session or requests.Session()
    found: list[Video] = []
    for query in list(queries)[:3]:
        if len(found) >= enough:
            break
        try:
            hits = _coverr_request(session, api_key, query, per_query)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"Signature {role} '{query}' failed: {type(exc).__name__}")
            continue
        for item in hits:
            vid = str(item.get("id", ""))
            urls = item.get("urls") or {}
            url = urls.get("mp4_download") or urls.get("mp4")
            if (not vid or vid in exclude or not url
                    or any(item.get(f) is True for f in ("is_premium", "premium", "is_sponsored",
                                                         "sponsored", "is_watermarked"))):
                continue
            exclude.add(vid)
            from .video import _coverr_creator_metadata
            name, link = _coverr_creator_metadata(item)
            found.append(Video(vid, "coverr", url=url, title=item.get("title", ""),
                               vertical=_is_portrait(item), creator_name=name, creator_url=link,
                               query=query, thumb_url=str(item.get("thumbnail") or item.get("poster") or ""),
                               tags=tuple(str(t).lower() for t in (item.get("tags") or []) if isinstance(t, str))[:30]))
        print(f"Signature {role} '{query}': {len(hits)} hits")
    return found


def rank(role: str, candidates: list[Video], workdir: Path) -> list[Video]:
    """Order by CLIP (positive − negative prompt similarity); keyword fallback."""
    prompts = PROMPTS.get(role)
    keyword = {"skater": "skate", "woman": "woman"}.get(role, "")
    fallback = sorted(candidates, key=lambda v: (keyword not in " ".join(v.tags + (v.title.lower(),)),
                                                 not v.vertical))
    if not prompts or not candidates:
        return fallback
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is None:
        return fallback
    from .curation import download_thumbnail
    try:
        import torch
        from PIL import Image
        model, preprocess, tokenizer = clip
        positive, negative = prompts
        with torch.no_grad():
            text = torch.nn.functional.normalize(model.encode_text(tokenizer(list(positive + negative))), dim=-1)
            scored = []
            for i, video in enumerate(candidates[:16]):
                thumb = download_thumbnail(video.thumb_url, workdir / f"sig_{role}_{i}.jpg")
                if thumb is None:
                    continue
                with Image.open(thumb) as img:
                    v = torch.nn.functional.normalize(
                        model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)
                thumb.unlink(missing_ok=True)
                sims = (v @ text.T)[0].tolist()
                score = max(sims[:len(positive)]) - max(sims[len(positive):]) + (0.01 if video.vertical else 0)
                scored.append((score, i))
        if not scored:
            return fallback
        order = [i for _, i in sorted(scored, key=lambda x: -x[0])]
        return [candidates[i] for i in order]
    except Exception as exc:
        print(f"Signature {role} ranking failed: {type(exc).__name__}")
        return fallback


def largest_face_ratio(path: Path, *, samples: int = 4, width: int = 480) -> float:
    """Height of the largest frontal face / frame height over a few frames (0 = none).

    Returns 0.0 when OpenCV is unavailable (check skipped).
    """
    try:
        import cv2
    except ImportError:
        return 0.0
    from .render import probe_dimensions
    src_w, src_h = probe_dimensions(path)
    if src_w <= 0 or src_h <= 0:
        return 0.0
    h = max(2, int(round(width * src_h / src_w / 2)) * 2)
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                           f"fps=1,scale={width}:{h},format=gray", "-frames:v", str(samples),
                           "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          capture_output=True, timeout=60)
    count = len(proc.stdout) // (width * h)
    if count < 1:
        return 0.0
    frames = np.frombuffer(proc.stdout[:count * width * h], dtype=np.uint8).reshape(count, h, width)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    worst = 0.0
    for frame in frames:
        for (_x, _y, _w, fh) in cascade.detectMultiScale(frame, scaleFactor=1.1, minNeighbors=6,
                                                         minSize=(24, 24)):
            worst = max(worst, fh / h)
    return float(worst)


def place_signature_shots(shots, durations: list[float], slots: dict[str, int]):
    """Ensure each signature source appears in one interior shot near its position.

    `slots` maps role → source index. Shots 0 and last stay (cover-matched bookends).
    """
    from .cinematic import Shot
    shots = list(shots)
    if len(shots) < 3:
        return shots
    # v4 footage must stay dominant (lesson from Creative v5): at most half of the
    # interior shots become signature shots; skater and woman before the cover motif.
    limit = max(1, (len(shots) - 2) // 2)
    chosen = sorted(slots.items(), key=lambda kv: PRIORITY.index(kv[0]) if kv[0] in PRIORITY else 9)[:limit]
    taken: set[int] = set()
    for role, source in sorted(chosen, key=lambda kv: SLOT_POSITION.get(kv[0], 0.5)):
        if any(s.source_index == source for s in shots[1:-1]):
            taken |= {i for i, s in enumerate(shots) if s.source_index == source}
            continue
        target = SLOT_POSITION.get(role, 0.5) * (len(shots) - 1)
        interior = [i for i in range(1, len(shots) - 1) if i not in taken]
        if not interior:
            break
        index = min(interior, key=lambda i: abs(i - target))
        length = shots[index].duration
        dur = durations[source]
        offset = max(0.0, (dur - length) / 2) if dur > length else 0.0
        shots[index] = Shot(source, round(offset, 3), length)
        taken.add(index)
    return shots
