"""Critic calibration against the owner's verdicts (Phase 5, 27 Nov).

The Visual Critic's thresholds are starting values. Here they are checked against what
the owner actually did: published (good), discarded or "worse than the last video" (bad).
Nothing changes automatically until there are at least MIN_VERDICTS verdicts with a
critic score: with fewer, the result is reported as "insufficient" (no spurious fitting).
With enough, the retry threshold becomes the midpoint between the median critic score of
good and bad Reels — only if the critic actually separates them (else "not predictive").
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

PATH = Path("data/critic-calibration.json")
MIN_VERDICTS = 20


def calibrate(decisions: dict, verdicts: dict) -> dict:
    worse = {int(v["issue"]) for v in (verdicts.get("verdicts") or [])}
    good, bad = [], []
    for d in decisions.get("decisions") or []:
        score = d.get("critic")
        if score is None:
            continue
        if d.get("decision") == "published":
            good.append(float(score))
        elif d.get("decision") == "discarded" or int(d.get("issue", 0)) in worse:
            bad.append(float(score))
    n = len(good) + len(bad)
    out = {"n_good": len(good), "n_bad": len(bad), "min_verdicts": MIN_VERDICTS}
    if n < MIN_VERDICTS or not good or not bad:
        return dict(out, status="insufficient")
    mg, mb = statistics.median(good), statistics.median(bad)
    if mg <= mb:
        return dict(out, status="not predictive", median_good=mg, median_bad=mb)
    return dict(out, status="calibrated", median_good=mg, median_bad=mb, retry_below=round((mg + mb) / 2, 3))


def retry_threshold(default: float) -> float:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return float(data["retry_below"]) if data.get("status") == "calibrated" else default
