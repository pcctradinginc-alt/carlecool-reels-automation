"""Bounded, local quality checks; aesthetic signals are not objective ratings."""
from pathlib import Path
import subprocess
import re
import math
import os

def inspect_reel(path, details, expected_duration):
    from .render import probe_duration, probe_dimensions
    path = Path(path)
    errors, warnings = [], []
    width, height = probe_dimensions(path)
    duration = probe_duration(path)
    expected_size = (270, 480) if os.getenv("CARLECOOL_OFFLINE_SMOKE") == "1" else (1080, 1920)
    if (width, height) != expected_size:
        errors.append(f"required resolution must be {expected_size[0]}x{expected_size[1]}")
    if abs(duration - expected_duration) > 0.25:
        errors.append("duration mismatch")
    p = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-xerror", "-i", str(path),
                        "-map", "0:v:0", "-map", "0:a:0", "-vf",
                        "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-50dB:d=0.75",
                        "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        errors.append("audio/video decode failed")
    if "black_start:" in p.stderr:
        warnings.append("black sequence detected")
    if "freeze_start:" in p.stderr:
        warnings.append("static sequence detected")
    volume = re.findall(r"max_volume:\s*(-inf|[-\d.]+) dB", p.stderr)
    if not volume:
        errors.append("audio level measurement missing")
    elif float(volume[-1]) < -35:
        errors.append("audio unexpectedly quiet")
    plan = details.get("edit_plan") or []
    distinct = len({s["source_index"] for s in plan})
    if not plan or distinct < math.ceil(len(plan) * .75):
        warnings.append("actual montage has repeated sources")
    return {"errors": errors, "warnings": warnings, "distinct_sources": distinct,
            "shots": len(plan), "duration": duration, "resolution": [width, height]}

def clip_metrics(path):
    """Sample actual decoded frames; no paid model calls."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(path))
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sharp, light, motion = [], [], []
    previous = None
    try:
        for f in (.15, .5, .85):
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frames*f)-1))
            ok, image = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(cv2.resize(image, (320, 180)), cv2.COLOR_BGR2GRAY)
            sharp.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            light.append(float(gray.mean()))
            if previous is not None:
                motion.append(float(np.abs(gray.astype(float)-previous).mean()))
            previous = gray.astype(float)
    finally:
        cap.release()
    return {"samples": len(sharp), "sharpness": round(float(np.median(sharp)), 2) if sharp else None,
            "brightness": round(float(np.median(light)), 2) if light else None,
            "motion": round(float(np.median(motion)), 2) if motion else None}

def ai_usable(metrics):
    return (metrics["samples"] >= 2 and metrics["brightness"] is not None
            and 8 < metrics["brightness"] < 247 and metrics["sharpness"] > 3
            and (metrics["motion"] or 0) > 0.2)
