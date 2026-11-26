"""Learning from the owner's decisions (26 Nov).

Every review issue ends in a decision: published (state.json `published`), discarded
("Nicht veröffentlichen" → `/reject` → "❌ Reel verworfen"), or none yet. The daily
performance job collects them into data/decisions.json; ranking (curation.py) reads it.

Signals are deliberately WEAK and gradual (one decision is not proof about every scene):
* published Reel → small plus for its clips and search motifs,
* discarded Reel → small minus for its clips and motifs,
* a motif only gets noticeably worse after repeated discards; nothing is ever banned.
Performance numbers stay a separate signal (performance.py).
"""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path("data/decisions.json")
CLIP_STEP, CLIP_CAP = 0.10, 0.30       # per discard / max. penalty for one clip
MOTIF_STEP, MOTIF_CAP = 0.05, 0.25     # per net discard / max. penalty for a search motif
BONUS_STEP, BONUS_CAP = 0.03, 0.10     # per publication / max. bonus


def collect(issues: list[dict], published_issues: set[int], comments_of) -> dict:
    """issues: GitHub issues with body; comments_of(number) → list of comment bodies."""
    from .review import decode_issue_data
    out = []
    for issue in issues:
        try:
            data = decode_issue_data(issue.get("body") or "")
        except (ValueError, json.JSONDecodeError):
            continue
        number = int(issue["number"])
        if number in published_issues:
            decision = "published"
        elif issue.get("state") == "closed" and any("Reel verworfen" in c for c in comments_of(number)):
            decision = "discarded"
        else:
            continue  # open / undecided: no signal
        facts = data.get("reel_facts") or {}
        sources = [s for s in data.get("footage_sources") or [] if s.get("used", True)]  # only clips really shown
        motifs = sorted({str(s.get("motif")).lower() for s in sources if s.get("motif")})
        shown = [str(s["id"]) for s in sources if s.get("id")] or list(data.get("video_ids") or [])
        out.append({"issue": number, "decision": decision, "video_ids": shown,
                    "motifs": motifs, "style": facts.get("style"), "variant": facts.get("variant"),
                    "theme": facts.get("theme"), "opening_clip": facts.get("opening_clip")})
    return {"version": 1, "decisions": sorted(out, key=lambda d: d["issue"])}


def load(path: Path = PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def scores(data: dict | None = None) -> tuple[dict[str, int], dict[str, int]]:
    """(clip id → net score, motif → net score); +1 per publication, −1 per discard."""
    clips: dict[str, int] = {}
    motifs: dict[str, int] = {}
    for d in (load() if data is None else data).get("decisions") or []:
        sign = 1 if d.get("decision") == "published" else -1 if d.get("decision") == "discarded" else 0
        for vid in d.get("video_ids") or []:
            clips[str(vid)] = clips.get(str(vid), 0) + sign
        for m in d.get("motifs") or []:
            motifs[m] = motifs.get(m, 0) + sign
    return clips, motifs


def adjustment(video, clip_scores: dict[str, int], motif_scores: dict[str, int]) -> float:
    """Ranking adjustment for one candidate (negative = later). Never a ban."""
    clip = clip_scores.get(str(getattr(video, "id", "")), 0)
    motif = motif_scores.get(str(getattr(video, "query", "") or "").lower(), 0)
    adj = 0.0
    if clip < 0:
        adj -= min(CLIP_CAP, CLIP_STEP * -clip)
    if motif < 0:
        adj -= min(MOTIF_CAP, MOTIF_STEP * -motif)
    positives = max(0, clip) + max(0, motif)
    return adj + min(BONUS_CAP, BONUS_STEP * positives)


def refresh(request=None, state: dict | None = None) -> dict:
    """Read all review issues and write data/decisions.json (performance job, daily)."""
    if request is None:
        from .review import github_request as request
    if state is None:
        from .state import load_state
        state = load_state()
    published = {int(p["approval_issue"]) for p in state.get("published", []) if p.get("approval_issue")}
    issues, page = [], 1
    while page <= 10:
        batch = request("GET", f"issues?labels=carlecool-review&state=all&per_page=100&page={page}") or []
        issues += [i for i in batch if "pull_request" not in i]
        if len(batch) < 100:
            break
        page += 1

    def comments_of(number):
        return [c.get("body") or "" for c in request("GET", f"issues/{number}/comments?per_page=100") or []]
    data = collect(issues, published, comments_of)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n_pub = sum(1 for d in data["decisions"] if d["decision"] == "published")
    print(f"Decisions: {n_pub} published, {len(data['decisions']) - n_pub} discarded")
    return data
