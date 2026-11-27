"""Shot Intelligence (owner's unified Creative Director plan, package B, 27 Nov).

Every clip gets a visual fingerprint ("Shot DNA") from frames sampled across the WHOLE
clip, and the strongest window inside it is found — so a Reel uses the best seconds of a
clip, not whatever comes first.

Per sample (about one per second, at most MAX_SAMPLES): brightness, contrast, Lab colour,
sharpness (Laplacian variance), motion (difference to the next sample), a hard-cut flag,
and — when OpenCLIP is available — the similarity to the owner's reference images of the
director's world and an image embedding. Per clip: the averages, the shot size (wide /
medium / close-up / detail, CLIP), the warmth, and the best window.

Everything runs locally on the runner (ffmpeg + numpy + the already loaded OpenCLIP);
no paid service, no upload.
"""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

SAMPLE_W, SAMPLE_H = 72, 128          # tiny 9:16 frames for the pixel statistics
MAX_SAMPLES = 24
EMBED_SAMPLES = 8                      # CLIP frames per clip (CPU budget)
WINDOW = 8.0                           # s kept per clip (opening clip needs ≥ 6 s for the loop)
CUT_JUMP = 28.0                        # mean grey difference that means a hard cut inside the clip
SHOT_SIZES = {
    "wide": "a wide establishing shot of a place, landscape or building",
    "medium": "a medium shot of a person or a scene",
    "close": "a close-up of a face, hands or an object",
    "detail": "an extreme close-up of a texture or a mechanical detail",
}


def _probe(path: Path) -> tuple[float, int, int]:
    """Duration and size via render's probes (they fall back to ffmpeg when ffprobe is missing)."""
    from .render import probe_dimensions, probe_duration
    try:
        duration = float(probe_duration(path))
    except Exception:
        duration = 0.0
    try:
        width, height = probe_dimensions(path)
    except Exception:
        width, height = 0, 0
    return duration, int(width), int(height)


def sample_frames(path: Path, duration: float, n: int):
    """n RGB frames (uint8, SAMPLE_H×SAMPLE_W×3) spread over the clip, with their times."""
    import numpy as np
    if duration <= 0 or n <= 0:
        return [], np.zeros((0, SAMPLE_H, SAMPLE_W, 3), dtype=np.uint8)
    fps = n / duration
    try:
        p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                            f"fps={fps:.5f},scale={SAMPLE_W}:{SAMPLE_H}:force_original_aspect_ratio=increase,"
                            f"crop={SAMPLE_W}:{SAMPLE_H},format=rgb24",
                            "-frames:v", str(n), "-f", "rawvideo", "-"], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return [], np.zeros((0, SAMPLE_H, SAMPLE_W, 3), dtype=np.uint8)
    size = SAMPLE_W * SAMPLE_H * 3
    count = len(p.stdout) // size
    frames = np.frombuffer(p.stdout[:count * size], dtype=np.uint8).reshape(count, SAMPLE_H, SAMPLE_W, 3)
    times = [min(duration - 0.05, (k + 0.5) / fps) for k in range(count)]
    return times, frames


def _lab(rgb):
    """Approximate CIE Lab (D65) of an RGB uint8 image → (L, a, b) means and stds."""
    import numpy as np
    c = rgb.reshape(-1, 3).astype(np.float32) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    lab = np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)
    return lab.mean(axis=0), lab.std(axis=0)


def _sharpness(gray) -> float:
    import numpy as np
    g = gray.astype(np.float32)
    lap = g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())


def pixel_stats(frames) -> list[dict]:
    import numpy as np
    out = []
    grays = [f.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32) for f in frames]
    for k, (f, g) in enumerate(zip(frames, grays)):
        lab_mean, lab_std = _lab(f)
        nxt = float(np.mean(np.abs(grays[k + 1] - g))) if k + 1 < len(grays) else None
        out.append({"luma": float(g.mean() / 255), "contrast": float((np.percentile(g, 90) - np.percentile(g, 10)) / 255),
                    "lab": [round(float(x), 2) for x in lab_mean], "lab_std": [round(float(x), 2) for x in lab_std],
                    "sharp": _sharpness(g), "motion": nxt})
    return out


def clip_embeddings(frames, clip, idx: list[int]):
    """Normalised CLIP embeddings of the frames at `idx` (torch tensor) or None."""
    if clip is None or not idx:
        return None
    try:
        import torch
        from PIL import Image
        model, preprocess, _ = clip
        batch = torch.stack([preprocess(Image.fromarray(frames[i])) for i in idx])
        with torch.no_grad():
            return torch.nn.functional.normalize(model.encode_image(batch), dim=-1)
    except Exception as exc:
        print("Shot analysis: CLIP unavailable:", type(exc).__name__)
        return None


def shot_size(vec, clip) -> str | None:
    if vec is None or clip is None:
        return None
    try:
        import torch
        model, _, tokenizer = clip
        with torch.no_grad():
            txt = torch.nn.functional.normalize(model.encode_text(tokenizer(list(SHOT_SIZES.values()))), dim=-1)
        sims = (txt @ vec).tolist()
        return list(SHOT_SIZES)[max(range(len(sims)), key=lambda i: sims[i])]
    except Exception:
        return None


def _norm(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    return [0.5 if hi - lo < 1e-9 else (v - lo) / (hi - lo) for v in values]


def frame_scores(stats: list[dict], ref: list[float | None]) -> list[float]:
    """Quality of each sample: closeness to the references, sharpness, lively but not shaky,
    well exposed. Hard cuts inside a clip are penalised later per window."""
    if not stats:
        return []
    sharp = _norm([s["sharp"] ** 0.5 for s in stats])
    move = [s["motion"] if s["motion"] is not None else (stats[-2]["motion"] if len(stats) > 1 and stats[-2]["motion"] is not None else 2.0)
            for s in stats]
    lively = [1.0 - min(1.0, abs(m - 6.0) / 6.0) for m in move]  # ~6 grey levels at 1 fps = calm, real movement
    exposure = [1.0 - min(1.0, abs(s["luma"] - 0.45) / 0.45) for s in stats]
    known = [r for r in ref if r is not None]
    refn = _norm([r if r is not None else (min(known) if known else 0.0) for r in ref]) if known else [0.5] * len(stats)
    return [0.45 * r + 0.2 * sh + 0.2 * lv + 0.15 * ex for r, sh, lv, ex in zip(refn, sharp, lively, exposure)]


def best_window(times: list[float], scores: list[float], stats: list[dict], duration: float,
                length: float = WINDOW) -> tuple[float, float]:
    """(start, length) of the strongest window; never across a hard cut when avoidable."""
    if duration <= length or not times:
        return 0.0, max(0.0, duration)
    best, best_val = 0.0, -1e9
    for k, t0 in enumerate(times):
        start = max(0.0, min(t0 - 0.5, duration - length))
        inside = [i for i, t in enumerate(times) if start <= t <= start + length]
        if not inside:
            continue
        val = sum(scores[i] for i in inside) / len(inside)
        cuts = sum(1 for i in inside[:-1] if stats[i]["motion"] is not None and stats[i]["motion"] > CUT_JUMP)
        val -= 0.25 * cuts
        if val > best_val + 1e-9:
            best, best_val = start, val
    return round(best, 2), round(length, 2)


ANALYSIS_VERSION = 2  # Phase 2: camera vs subject motion, direction, noise, blockiness, subject position, edges, HDR


def flow_stats(frames) -> dict:
    """OpenCV Farneback flow between consecutive samples (72×128): camera motion = median
    vector, subject motion = residual magnitude, direction of the camera move in degrees."""
    import numpy as np
    try:
        import cv2
    except ImportError:
        return {}
    grays = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in frames]
    cams, subj, angles = [], [], []
    for a, b in zip(grays, grays[1:]):
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 2, 9, 2, 5, 1.1, 0)
        med = np.median(flow.reshape(-1, 2), axis=0)
        cams.append(float(np.hypot(*med)))
        subj.append(float(np.hypot(flow[..., 0] - med[0], flow[..., 1] - med[1]).mean()))
        angles.append(float(np.degrees(np.arctan2(med[1], med[0]))))
    if not cams:
        return {}
    return {"camera_motion": round(float(np.mean(cams)), 3), "subject_motion": round(float(np.mean(subj)), 3),
            "camera_direction": round(float(np.median(angles)), 1)}


def texture_stats(frames) -> dict:
    """Noise / grain (high-pass residual), compression blockiness (8-px grid), subject
    position (centre of edge energy, 0..1)."""
    import numpy as np
    try:
        import cv2
    except ImportError:
        return {}
    noise, block, cx, cy = [], [], [], []
    for f in frames:
        g = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32)
        noise.append(float(np.std(g - cv2.GaussianBlur(g, (3, 3), 0))))
        dx = np.abs(np.diff(g, axis=1))
        grid = dx[:, 7::8].mean() if dx.shape[1] > 8 else 0.0
        block.append(float(grid / (dx.mean() + 1e-6)))
        sob = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
        total = sob.sum() + 1e-6
        ys, xs = np.mgrid[0:g.shape[0], 0:g.shape[1]]
        cx.append(float((sob * xs).sum() / total / g.shape[1]))
        cy.append(float((sob * ys).sum() / total / g.shape[0]))
    return {"noise": round(float(np.mean(noise)), 3), "blockiness": round(float(np.mean(block)), 3),
            "subject_x": round(float(np.mean(cx)), 3), "subject_y": round(float(np.mean(cy)), 3)}


def is_hdr(path: Path) -> str | bool:
    """HDR transfer of the clip ("smpte2084" = PQ, "arib-std-b67" = HLG) or False."""
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return next((t for t in ("smpte2084", "arib-std-b67") if t in p.stderr), False)


def _file_key(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:20]


def cached_analyze(path: Path, *, clip=None, references=None, cache_dir: Path | None = None) -> dict:
    """analyze() cached by file hash + analysis version (+ whether CLIP / references were used)."""
    import json
    cache_dir = cache_dir or Path(os.getenv("CARLECOOL_LIBRARY_DIR", "footage-cache")) / "dna"
    tag = f"{_file_key(Path(path))}_v{ANALYSIS_VERSION}_{'c' if clip is not None else 'n'}{'r' if references is not None else ''}"
    target = cache_dir / f"{tag}.json"
    if target.is_file():
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            pass
    dna = analyze(path, clip=clip, references=references)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(dna), encoding="utf-8")
    except OSError:
        pass
    return dna


def _b64(vec) -> str:
    import numpy as np
    return base64.b64encode(np.asarray(vec, dtype=np.float16).tobytes()).decode("ascii")


def decode_embedding(text: str):
    import numpy as np
    return np.frombuffer(base64.b64decode(text), dtype=np.float16).astype("float32")


def analyze(path: Path, *, clip=None, references=None) -> dict:
    """Shot DNA of one clip. `references`: normalised reference vectors (stylegate.load_neighbors)."""
    duration, width, height = _probe(Path(path))
    n = max(2, min(MAX_SAMPLES, int(duration))) if duration > 0 else 0
    times, frames = sample_frames(Path(path), duration, n)
    stats = pixel_stats(frames)
    ref: list[float | None] = [None] * len(stats)
    emb_mean = None
    size = None
    if len(stats):
        step = max(1, len(stats) // EMBED_SAMPLES)
        idx = list(range(0, len(stats), step))[:EMBED_SAMPLES]
        vecs = clip_embeddings(frames, clip, idx)
        if vecs is not None:
            if references is not None:
                from .stylegate import neighbor_score
                for i, v in zip(idx, vecs):
                    ref[i] = neighbor_score(v, references)
                # frames between the embedded ones take the nearest embedded value
                for i in range(len(ref)):
                    if ref[i] is None:
                        ref[i] = ref[min(idx, key=lambda j: abs(j - i))]
            import torch
            mean = torch.nn.functional.normalize(vecs.mean(dim=0), dim=-1)
            emb_mean = mean.tolist()
            size = shot_size(mean, clip)
    scores = frame_scores(stats, ref)
    start, length = best_window(times, scores, stats, duration)
    inside = [i for i, t in enumerate(times) if start <= t <= start + length] or list(range(len(stats)))
    extra = {}
    if len(stats):
        win = frames[inside[0]:inside[-1] + 1]
        extra.update(flow_stats(win))
        extra.update(texture_stats(win))
        # edge frames of the window: transitions are judged on the real cut frames (Phase 3)
        edge_vecs = clip_embeddings(frames, clip, [inside[0], inside[-1]]) if clip is not None else None
        extra["edge_in"] = {"lab": stats[inside[0]]["lab"], "luma": stats[inside[0]]["luma"],
                            "embedding": _b64(edge_vecs[0].tolist()) if edge_vecs is not None else None}
        extra["edge_out"] = {"lab": stats[inside[-1]]["lab"], "luma": stats[inside[-1]]["luma"],
                             "embedding": _b64(edge_vecs[1].tolist()) if edge_vecs is not None else None}
    extra["hdr"] = is_hdr(Path(path))
    extra["version"] = ANALYSIS_VERSION

    def avg(key, idx=inside):
        vals = [stats[i][key] for i in idx if stats[i][key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None
    lab = [round(sum(stats[i]["lab"][c] for i in inside) / len(inside), 2) for c in range(3)] if inside and stats else None
    refs = [ref[i] for i in inside if ref[i] is not None]
    return {
        "duration": round(duration, 2), "width": width, "height": height,
        "best_start": start, "best_length": length,
        "luma": avg("luma"), "contrast": avg("contrast"), "sharpness": avg("sharp"), "motion": avg("motion"),
        "lab": lab, "warmth": (round(lab[2] - abs(lab[1]) * 0.2, 2) if lab else None),
        "ref_score": round(sum(refs) / len(refs), 4) if refs else None,
        "quality": round(sum(scores[i] for i in inside) / len(inside), 4) if scores and inside else None,
        "shot_size": size, "embedding": _b64(emb_mean) if emb_mean is not None else None,
        "samples": len(stats), **extra,
    }


def cut_to_window(path: Path, dna: dict, dest: Path) -> Path:
    """Keep only the best window (lossless re-encode, frame-accurate); returns the new path."""
    duration = float(dna.get("duration") or 0)
    start, length = float(dna.get("best_start") or 0), float(dna.get("best_length") or 0)
    if duration <= 0 or (start <= 0.05 and length >= duration - 0.1):
        return Path(path)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", str(path), "-t", f"{length:.3f}",
                    "-an", "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", str(dest)],
                   check=True, capture_output=True, timeout=300)
    return dest
