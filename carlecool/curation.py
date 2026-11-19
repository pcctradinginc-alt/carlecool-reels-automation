"""Cover-led footage curation: derive search phrases from the album cover and rank
candidate clips by their thumbnails BEFORE any video download.

With OpenCLIP (CARLECOOL_SEMANTIC=on): cover and thumbnails are embedded and compared;
the cover also chooses the closest art-direction phrases. Without it, a colour
fingerprint (warmth, brightness, saturation) is used. Every step is optional: on
failure the profile's own lane sampling and the original candidate order remain.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import numpy as np
import requests

from .creative import CUES, LANES
from .video import Video, _check_host

MAX_THUMB_BYTES = 2_000_000


def _cover_rgb(path: Path, size: int = 32) -> np.ndarray:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1",
                           "-vf", f"scale={size}:{size}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                          capture_output=True, timeout=30, check=True)
    if len(proc.stdout) != size * size * 3:
        raise ValueError("Invalid image decode")
    return np.frombuffer(proc.stdout, dtype=np.uint8).reshape(-1, 3).astype(np.float64) / 255.0


def palette_traits(path: Path) -> dict:
    px = _cover_rgb(path)
    brightness = float(np.median(px.mean(axis=1)))
    saturation = float(np.mean(px.max(axis=1) - px.min(axis=1)))
    warmth = float(np.mean(px[:, 0] - px[:, 2]))
    greenness = float(np.mean(px[:, 1] - (px[:, 0] + px[:, 2]) / 2))
    return {"brightness": round(brightness, 3), "saturation": round(saturation, 3),
            "warmth": round(warmth, 3), "greenness": round(greenness, 3)}


def lane_scores_from_palette(traits: dict) -> dict:
    """Readable colour → mood mapping (no model): warm/bright → Americana, dark → night…"""
    b, s, w, g = (traits["brightness"], traits["saturation"], traits["warmth"], traits["greenness"])
    return {
        "americana": 1.0 + 4 * max(0.0, w) + 1.5 * max(0.0, b - 0.45),
        "nature": 1.0 + 6 * max(0.0, g) + 2 * max(0.0, 0.2 - s) + (0.5 if b > 0.55 else 0),
        "studio": 1.0 + 2 * max(0.0, 0.18 - s) + 1 * max(0.0, 0.45 - b),
        "skate": 0.8 + 1.5 * max(0.0, s - 0.25) + 1.0 * max(0.0, w),
        "y2k": 0.5 + 2 * max(0.0, s - 0.35),
        "night": 0.5 + 6 * max(0.0, 0.3 - b) + 3 * max(0.0, -w),
    }


def _pick_phrase(lane: str, key: str) -> str:
    phrases = CUES[lane]
    index = int.from_bytes(hashlib.sha256(f"{lane}|{key}".encode()).digest()[:2], "big")
    return phrases[index % len(phrases)]


def cover_queries(cover: Path, weights: dict, *, run_key: str = "", count: int = 2) -> dict:
    """Return {"queries": [...], "lanes": [...], "method": ...} chosen by the cover.

    Profile weights still matter (a lane weighted 0 is never chosen), but the cover decides
    which of the allowed directions comes first.
    """
    allowed = [lane for lane in LANES if int(weights.get(lane, 0)) > 0]
    if not allowed:
        return {"queries": [], "lanes": [], "method": "none"}
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is not None:
        try:
            import torch
            from .semantic import _frame
            model, preprocess, tokenizer = clip
            phrases = [(lane, phrase) for lane in allowed for phrase in CUES[lane]]
            with torch.no_grad():
                img = model.encode_image(preprocess(_frame(cover, 0)).unsqueeze(0))
                img = torch.nn.functional.normalize(img, dim=-1)
                txt = model.encode_text(tokenizer([f"A cinematic frame of {p}." for _, p in phrases]))
                txt = torch.nn.functional.normalize(txt, dim=-1)
                sims = (img @ txt.T)[0].tolist()
            prior = {lane: 0.002 * int(weights.get(lane, 0)) for lane in allowed}
            ranked = sorted(range(len(phrases)), key=lambda i: -(sims[i] + prior[phrases[i][0]]))
            queries, lanes = [], []
            for i in ranked:
                lane, phrase = phrases[i]
                if lane in lanes:
                    continue
                queries.append(phrase)
                lanes.append(lane)
                if len(queries) >= count:
                    break
            return {"queries": queries, "lanes": lanes, "method": "openclip"}
        except Exception as exc:
            print("Cover phrase selection via OpenCLIP failed:", type(exc).__name__)
    try:
        traits = palette_traits(cover)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"queries": [], "lanes": [], "method": "none"}
    scores = lane_scores_from_palette(traits)
    combined = {lane: scores[lane] * (0.5 + int(weights.get(lane, 0)) / 50) for lane in allowed}
    lanes = sorted(allowed, key=lambda lane: -combined[lane])[:count]
    return {"queries": [_pick_phrase(lane, run_key) for lane in lanes], "lanes": lanes,
            "method": "palette", "traits": traits}


def merge_queries(cover_choice: dict, profile_queries: list[str], limit: int = 3) -> list[str]:
    """Cover phrases first, then the profile's own sampling for variety."""
    out = []
    for phrase in list(cover_choice.get("queries", [])) + list(profile_queries):
        lane = next((l for l, items in CUES.items() if phrase in items), phrase)
        if phrase in out or any(lane == next((l for l, items in CUES.items() if q in items), q) for q in out):
            continue
        out.append(phrase)
        if len(out) >= limit:
            break
    for phrase in profile_queries:
        if len(out) >= limit:
            break
        if phrase not in out:
            out.append(phrase)
    return out[:limit]


def download_thumbnail(url: str, destination: Path, *, session=None) -> Path | None:
    if not url:
        return None
    try:
        _check_host(url)
        session = session or requests.Session()
        response = session.get(url, timeout=(10, 20), stream=True, allow_redirects=False)
        try:
            if response.status_code != 200:
                return None
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_THUMB_BYTES:
                    return None
        finally:
            response.close()
        if len(data) < 512:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bytes(data))
        return destination
    except (requests.RequestException, OSError, ValueError):
        return None


def _palette_vector(path: Path) -> np.ndarray:
    px = _cover_rgb(path)
    brightness = px.mean(axis=1)
    saturation = px.max(axis=1) - px.min(axis=1)
    return np.concatenate([px.mean(axis=0), [np.median(brightness), np.mean(saturation)]])


def score_thumbnails(cover: Path | None, thumbs: list[Path | None], queries: list[str]) -> list[float]:
    """Higher is better. CLIP: 0.7·cover similarity + 0.3·query-text similarity."""
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is not None:
        try:
            import torch
            from PIL import Image
            model, preprocess, tokenizer = clip
            with torch.no_grad():
                cover_vec = None
                if cover is not None:
                    with Image.open(cover) as img:
                        cover_vec = torch.nn.functional.normalize(
                            model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)
                unique = sorted(set(queries))
                text = torch.nn.functional.normalize(model.encode_text(
                    tokenizer([f"A cinematic frame of {q}." for q in unique])), dim=-1)
                text_index = {q: i for i, q in enumerate(unique)}
                scores = []
                for thumb, query in zip(thumbs, queries):
                    if thumb is None:
                        scores.append(-1.0)
                        continue
                    with Image.open(thumb) as img:
                        v = torch.nn.functional.normalize(
                            model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)
                    text_sim = float((v @ text[text_index[query]].unsqueeze(1)).item())
                    cover_sim = float((v @ cover_vec.T).item()) if cover_vec is not None else text_sim
                    scores.append(round(0.7 * cover_sim + 0.3 * text_sim, 5))
                return scores
        except Exception as exc:
            print("Thumbnail CLIP scoring failed; palette fallback:", type(exc).__name__)
    if cover is None:
        return [0.0 if t is not None else -1.0 for t in thumbs]
    try:
        ref = _palette_vector(cover)
    except (OSError, ValueError, subprocess.SubprocessError):
        return [0.0 if t is not None else -1.0 for t in thumbs]
    out = []
    for thumb in thumbs:
        try:
            if thumb is None:
                raise ValueError("missing")
            distance = float(np.linalg.norm((_palette_vector(thumb) - ref) * [1, 1, 1, .5, .5]))
            out.append(round(1.0 - distance / 2.0, 5))
        except (OSError, ValueError, subprocess.SubprocessError):
            out.append(-1.0)
    return out


def rank_candidates(candidates: list[Video], cover: Path | None, workdir: Path, *,
                    keep: int = 7, session=None) -> tuple[list[Video], list[dict]]:
    """Pick the `keep` best candidates before downloading any full video.

    Keeps at least one clip per search lane when possible (variety), then fills by score.
    Candidates without a thumbnail (e.g. owned fallback stock) keep a neutral score and
    stay after the scored stock clips.
    """
    remote = [c for c in candidates if c.source == "coverr"]
    others = [c for c in candidates if c.source != "coverr"]
    if len(remote) <= keep:
        return candidates, []
    thumbs = [download_thumbnail(c.thumb_url, workdir / f"thumb_{i:02d}.jpg", session=session)
              for i, c in enumerate(remote)]
    scores = score_thumbnails(cover, thumbs, [c.query or c.title for c in remote])
    for thumb in thumbs:
        if thumb is not None:
            thumb.unlink(missing_ok=True)
    if not any(score > -1 for score in scores):
        # No thumbnail could be scored: keep discovery order, never lose all stock.
        return remote[:keep] + others, []
    # Portrait clips always rank ahead of landscape fill-ins (which need a 9:16 crop).
    rank = [scores[i] + (1.0 if remote[i].vertical else 0.0) for i in range(len(remote))]
    order = sorted(range(len(remote)), key=lambda i: (-rank[i], i))
    chosen: list[int] = []
    for lane in dict.fromkeys(c.query for c in remote):
        best = next((i for i in order if remote[i].query == lane and scores[i] > -1
                     and (remote[i].vertical or not any(r.vertical for r in remote))), None)
        if best is not None and best not in chosen:
            chosen.append(best)
    for i in order:
        if len(chosen) >= keep:
            break
        if i not in chosen and scores[i] > -1:
            chosen.append(i)
    chosen = sorted(chosen[:keep], key=lambda i: -rank[i])
    report = [{"id": remote[i].id, "query": remote[i].query, "score": scores[i]} for i in chosen]
    from dataclasses import replace
    picked = [replace(remote[i], score=float(scores[i])) for i in chosen]
    return picked + others, report
