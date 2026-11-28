"""Creative Compatibility Filter + Viral Integration Protocol (owner, 28 Nov).

A trend is never taken because it is popular. Score (0–100), owner's starting weights:
CarleCool DNA 30 · musical fit 20 · coherence with the film idea 20 · viral momentum 15 ·
freshness 10 · originality 5. Hard vetoes: unclear rights, no translation into this
director's world, expired, the song does not fit, it collides with the director's
exclusions. At most ONE trend mechanism per Reel; "no suitable trend" is a valid result;
the artist's music is never replaced. 70 / 20 / 10 across all Reels: signature / trend-
adapted / experiment. Shadow mode (default): the decision is recorded and shown in the
review mail but does not change the Reel; CARLECOOL_TREND_MODE=active applies it.
"""
from __future__ import annotations

import hashlib
import os

WEIGHTS = {"dna": 0.30, "music": 0.20, "film": 0.20, "momentum": 0.15, "freshness": 0.10, "originality": 0.05}
THRESHOLD = 70.0          # trend-adapted Reels
EXPERIMENT_THRESHOLD = 55.0
SHARES = {"signature": 0.70, "trend": 0.20, "experiment": 0.10}
PROTOCOL = (
    "The artist's identity, music and cinematic coherence always take precedence over virality.",
    "Identify the underlying creative mechanism of a verified trend rather than copying its surface.",
    "Translate it into the selected Lana or Night world.",
    "Integrate at most one dominant trend mechanism per Reel.",
    "Never introduce an unrelated motif merely because it is trending.",
    "Never replace the artist's music with trending audio.",
    "Reject any trend that weakens the film idea, emotional authenticity or visual consistency.",
    "No suitable trend is a valid result.",
    "Record source, freshness, compatibility, adaptation and rejection reasons in the Creative Plan.",
)


def mode() -> str:
    m = os.getenv("CARLECOOL_TREND_MODE", "shadow").strip().lower()
    return m if m in ("shadow", "active", "off") else "shadow"


def bucket(previews: list[dict], run_key: str) -> str:
    """70 / 20 / 10 over all Reels: the bucket furthest below its share comes next."""
    used = [p.get("trend_bucket") for p in previews if p.get("trend_bucket") in SHARES]
    n = len(used) + 1
    deficit = {b: SHARES[b] * n - used.count(b) for b in SHARES}
    best = max(deficit.values())
    tied = [b for b in SHARES if abs(deficit[b] - best) < 1e-9]
    return tied[int.from_bytes(hashlib.sha256(f"{run_key}|trendbucket".encode()).digest()[:2], "big") % len(tied)]


def score(trend: dict, *, director: str | None, theme: str | None, music_classes: dict,
          exclusions: list[str], recent_ids: list[str], google_topics: list[str] | None = None) -> dict:
    """{"score", "parts", "veto": reason | None, "adaptation"}."""
    from . import trend_intelligence as ti
    from .themes import ORDER
    tr = (trend.get("translations") or {}).get(director or "")
    if not trend.get("rights_ok", False):
        return {"score": 0.0, "veto": "unclear usage rights", "parts": {}}
    if tr is None:
        return {"score": 0.0, "veto": f"no translation into the {director} world", "parts": {}}
    from . import directors as _d
    allowed = ((_d.get(director) or {}).get("trend_rules") or {}).get("allowed_categories")
    if allowed and trend.get("category") not in allowed:
        return {"score": 0.0, "veto": f"category '{trend.get('category')}' not allowed for {director}", "parts": {}}
    if ti.freshness(trend) <= 0:
        return {"score": 0.0, "veto": "expired", "parts": {}}
    mech = (trend.get("mechanism") or "").lower()
    if any(e and e.lower() in mech for e in exclusions):
        return {"score": 0.0, "veto": "collides with the director's exclusions", "parts": {}}
    # music: same class 1, neighbouring 0.5, else 0 (as themes.music_fit)
    num = den = 0.0
    for dim, want in (trend.get("music") or {}).items():
        have = music_classes.get(dim)
        if have is None or dim not in ORDER:
            continue
        steps = abs(ORDER[dim].index(have) - ORDER[dim].index(want))
        num += 1.0 if steps == 0 else (0.5 if steps == 1 and len(ORDER[dim]) > 2 else 0.0)
        den += 1.0
    music = num / den if den else 0.5
    if music < 0.3:
        return {"score": 0.0, "veto": "the song does not fit the mechanism", "parts": {"music": music}}
    themes_ok = tr.get("themes") or []
    film = 1.0 if theme in themes_ok else 0.4
    dna = 1.0 if theme in themes_ok else 0.7
    parts = {"dna": dna, "music": round(music, 3), "film": film,
             "momentum": ti.momentum(trend, google_topics), "freshness": ti.freshness(trend),
             "originality": 0.3 if trend.get("id") in recent_ids else 1.0}
    total = round(100 * sum(WEIGHTS[k] * parts[k] for k in WEIGHTS), 1)
    return {"score": total, "veto": None, "parts": parts,
            "adaptation": {"text": tr.get("text"), "mechanism": trend.get("mechanism"), "themes": themes_ok}}


def decide(*, director: str | None, theme: str | None, music_classes: dict, previews: list[dict],
           run_key: str, google_topics: list[str] | None = None, trends: list[dict] | None = None) -> dict:
    """The trend decision of this Reel (recorded in the Creative Plan, shown in the mail)."""
    from . import directors, trend_intelligence as ti
    if mode() == "off":
        return {"mode": "off", "bucket": "signature", "chosen": None, "considered": []}
    b = bucket(previews, run_key)
    exclusions = list((directors.get(director) or {}).get("exclusions") or [])
    recent = [p.get("trend_id") for p in previews[-6:] if p.get("trend_id")]
    considered = []
    for t in ti.active(trends if trends is not None else ti.load()):
        r = score(t, director=director, theme=theme, music_classes=music_classes, exclusions=exclusions,
                  recent_ids=recent, google_topics=google_topics)
        considered.append({"id": t.get("id"), "name": t.get("name"), "category": t.get("category"),
                           "evidence": ti.evidence_quality(t), "score": r["score"], "veto": r["veto"],
                           "parts": r.get("parts"), "adaptation": r.get("adaptation")})
    considered.sort(key=lambda c: -c["score"])
    threshold = THRESHOLD if b == "trend" else EXPERIMENT_THRESHOLD if b == "experiment" else None
    chosen = None
    if threshold is not None:
        chosen = next((c for c in considered if not c["veto"] and c["score"] >= threshold), None)
    return {"mode": mode(), "bucket": b, "chosen": chosen, "considered": considered[:4],
            "note": None if chosen or b == "signature" else "no suitable trend (a valid result)"}
