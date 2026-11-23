"""Performance learning from REAL platform numbers (Zernio analytics).

1. Collect (daily workflow `performance.yml`): for every Reel published via Zernio
   (data/state.json → provider_post_id) the post metrics are fetched at three
   checkpoints — 2, 7 and 28 days after publishing — with GET /v1/analytics?postId=…
   and stored in data/performance.json (views, shares, saves, comments, likes, average
   watch time, completion rate, replays — whatever the platform returns).
2. Score: per post and platform, engagement that signals "people want more of this":
   shares and saves weigh most, then comments, likes; plus watch time relative to the
   video length (or the completion rate). Each post is compared with the median of the
   owner's own posts on that platform (no absolute targets).
3. Learn (data/performance-model.json): variants are compared only when BOTH sides have
   at least MIN_POSTS posts and differ by at least MIN_LIFT. Learned:
     * Reel length (short ≈15–20 s vs long ≈24–30 s) → used by the length test,
     * signature roles (gear, friends, flag, car …) → placement priority,
     * caption question yes/no → how often a question is asked.
   Style worlds are only REPORTED: the owner's rules (cover/music/song memory) decide.
4. Owner choices (/revise, remembered song styles) always win over learned weights.
No personal data is stored: only public post metrics and our own Reel facts.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import time

DATA_PATH = Path("data/performance.json")
MODEL_PATH = Path("data/performance-model.json")
CHECKPOINTS = (("d2", 2), ("d7", 7), ("d28", 28))
MIN_POSTS = 4          # per variant before anything is adjusted
MIN_LIFT = 0.15        # +15 % median score difference
SHORT_TARGET = 18.0   # owner 23 Nov: never shorter than 15 s
METRICS = ("views", "impressions", "reach", "likes", "comments", "shares", "saves", "reposts",
           "igReelsAvgWatchTime", "completionRate", "replays", "videoDurationSeconds", "engagementRate")


# ---------------------------------------------------------------- collecting

def due_checkpoints(published_at: str, done: dict, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    try:
        at = datetime.fromisoformat(published_at)
    except (TypeError, ValueError):
        return []
    return [name for name, days in CHECKPOINTS
            if name not in done and now - at >= timedelta(days=days)]


def parse_analytics(payload: dict) -> dict[str, dict]:
    """{platform: {metric: number, "url": …}} from a GET /v1/analytics?postId=… answer."""
    post = payload.get("post") if isinstance(payload.get("post"), dict) else payload
    if isinstance(payload.get("posts"), list) and payload["posts"]:
        post = payload["posts"][0]
    out: dict[str, dict] = {}
    for entry in (post or {}).get("platformAnalytics") or []:
        platform = str(entry.get("platform") or "").lower()
        stats = entry.get("analytics") or {}
        if not platform or not isinstance(stats, dict):
            continue
        values = {k: float(stats[k]) for k in METRICS
                  if isinstance(stats.get(k), (int, float)) and not isinstance(stats.get(k), bool)}
        if entry.get("platformPostUrl"):
            values["url"] = str(entry["platformPostUrl"])
        out[platform] = values
    if not out and isinstance((post or {}).get("analytics"), dict):
        stats = post["analytics"]
        out["all"] = {k: float(stats[k]) for k in METRICS if isinstance(stats.get(k), (int, float))}
    return out


class AnalyticsUnavailable(RuntimeError):
    pass


def fetch_post(post_id: str, *, session=None, key: str | None = None) -> dict[str, dict] | None:
    """Metrics of one Zernio post; None while Zernio is still syncing (202)."""
    import requests
    key = key or os.getenv("ZERNIO_API_KEY", "").strip()
    if not key:
        raise AnalyticsUnavailable("ZERNIO_API_KEY is not configured")
    session = session or requests.Session()
    r = session.get("https://zernio.com/api/v1/analytics", params={"postId": post_id},
                    headers={"Authorization": "Bearer " + key}, timeout=30)
    if r.status_code == 402:
        raise AnalyticsUnavailable("Zernio answered 402: the Analytics add-on is required for this plan")
    if r.status_code in (202, 424):
        return None
    if r.status_code == 429:
        time.sleep(float(r.headers.get("Retry-After") or 5))
        return None
    r.raise_for_status()
    return parse_analytics(r.json())


def collect(state: dict, data: dict, *, fetch=fetch_post, now: datetime | None = None) -> int:
    """Add due checkpoints for all Zernio posts; returns the number of new snapshots."""
    posts = data.setdefault("posts", {})
    added = 0
    for record in state.get("published", []):
        post_id = record.get("provider_post_id")
        if record.get("provider") != "zernio" or not post_id:
            continue
        entry = posts.setdefault(post_id, {"track_id": record.get("track_id"), "at": record.get("at"),
                                           "target": record.get("target"), "facts": record.get("reel_facts") or {},
                                           "checkpoints": {}})
        if record.get("reel_facts") and not entry.get("facts"):
            entry["facts"] = record["reel_facts"]
        for name in due_checkpoints(str(record.get("at") or ""), entry["checkpoints"], now):
            metrics = fetch(post_id)
            if metrics is None:
                print(f"Analytics for {post_id} not synced yet ({name}); next run retries")
                break
            entry["checkpoints"][name] = {"fetched": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
                                          "platforms": metrics}
            added += 1
            print(f"Analytics {post_id} {name}: " + ", ".join(
                f"{p}: {int(m.get('views', 0))} views, {int(m.get('shares', 0))} shares"
                for p, m in metrics.items()))
    data["updated"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return added


# ---------------------------------------------------------------- scoring + model

def post_score(metrics: dict) -> float | None:
    """Engagement per view with shares/saves weighted highest, plus watch quality."""
    views = metrics.get("views") or metrics.get("impressions") or 0
    if views < 20:
        return None
    eng = (3 * metrics.get("shares", 0) + 3 * metrics.get("saves", 0) + 2 * metrics.get("reposts", 0)
           + 2 * metrics.get("comments", 0) + metrics.get("likes", 0)) / views
    watch = None
    if metrics.get("completionRate"):
        watch = float(metrics["completionRate"]) / (100.0 if metrics["completionRate"] > 1 else 1.0)
    elif metrics.get("igReelsAvgWatchTime") and metrics.get("videoDurationSeconds"):
        avg = float(metrics["igReelsAvgWatchTime"])
        avg = avg / 1000.0 if avg > 1000 else avg  # ms or s
        watch = min(2.0, avg / max(1.0, float(metrics["videoDurationSeconds"])))
    return eng * 10 + (watch if watch is not None else 0.0)


def _latest(entry: dict) -> dict:
    for name in ("d28", "d7", "d2"):
        if name in entry.get("checkpoints", {}):
            return entry["checkpoints"][name]["platforms"]
    return {}


def observations(data: dict) -> list[dict]:
    """One row per (post, platform) with a score relative to that platform's median."""
    rows = []
    for post_id, entry in (data.get("posts") or {}).items():
        for platform, metrics in _latest(entry).items():
            score = post_score(metrics)
            if score is not None:
                rows.append({"post": post_id, "platform": platform, "score": score,
                             "facts": entry.get("facts") or {}})
    by_platform: dict[str, list[float]] = {}
    for row in rows:
        by_platform.setdefault(row["platform"], []).append(row["score"])
    for row in rows:
        median = statistics.median(by_platform[row["platform"]]) or 1e-9
        row["relative"] = row["score"] / median
    return rows


def _compare(rows, predicate) -> dict | None:
    yes = [r["relative"] for r in rows if predicate(r["facts"]) is True]
    no = [r["relative"] for r in rows if predicate(r["facts"]) is False]
    result = {"n_yes": len(yes), "n_no": len(no)}
    if len(yes) < MIN_POSTS or len(no) < MIN_POSTS:
        return dict(result, decided=False)
    lift = statistics.median(yes) / max(1e-9, statistics.median(no)) - 1
    return dict(result, lift=round(lift, 3), decided=abs(lift) >= MIN_LIFT)


def build_model(data: dict) -> dict:
    rows = observations(data)
    model = {"version": 1, "observations": len(rows), "min_posts": MIN_POSTS, "min_lift": MIN_LIFT,
             "length": None, "roles": {}, "question": None, "styles": {}}
    length = _compare(rows, lambda f: None if "length_bucket" not in f else f["length_bucket"] == "short")
    if length:
        model["length"] = dict(length, prefer=("short" if length.get("lift", 0) > 0 else "long")
                               if length.get("decided") else None)
    for role in ("gear", "friends", "flag", "car", "americana", "skater", "woman", "friends2"):
        cmp_ = _compare(rows, lambda f, r=role: None if "roles" not in f else r in f["roles"])
        if cmp_:
            model["roles"][role] = cmp_
    question = _compare(rows, lambda f: None if "question" not in f else bool(f["question"]))
    if question:
        model["question"] = question
    for world in ("lana", "rubin"):  # report only
        vals = [r["relative"] for r in rows if r["facts"].get("style") == world]
        if vals:
            model["styles"][world] = {"n": len(vals), "median_relative": round(statistics.median(vals), 3)}
    return model


def load_model(path: Path = MODEL_PATH) -> dict:
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
        return model if isinstance(model, dict) and model.get("version") == 1 else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- applying (main.py)

def bucket(length: float) -> str:
    return "short" if float(length) <= 20 else "long"


def _share(key: str) -> float:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") / 65535.0


def choose_length(track_id: str, previews: list[dict], long_target: float, run_key: str,
                  model: dict | None = None) -> dict:
    """Length test: each song gets both lengths in turn; once the data shows a winner,
    the winner is used ~70 % of the time (the other stays in to notice changes)."""
    if os.getenv("CARLECOOL_LENGTH_TEST", "on").strip().lower() in ("off", "false", "0", "no"):
        return {"bucket": "long", "target": float(long_target), "reason": "length test off"}
    model = model or {}
    prefer = ((model.get("length") or {}).get("prefer"))
    if prefer in ("short", "long"):
        chosen = prefer if _share(f"{run_key}|length") < 0.7 else ("long" if prefer == "short" else "short")
        reason = f"learned: {prefer} performs better (70/30)"
    else:
        used = [p.get("length_bucket") for p in previews
                if str(p.get("track_id")) == str(track_id) and p.get("length_bucket")]
        shorts, longs = used.count("short"), used.count("long")
        if shorts != longs:
            chosen = "short" if shorts < longs else "long"
        else:
            chosen = "short" if _share(f"{run_key}|length") < 0.5 else "long"
        reason = f"A/B test (this song so far: {shorts}× short, {longs}× long)"
    return {"bucket": chosen, "target": SHORT_TARGET if chosen == "short" else float(long_target),
            "reason": reason}


def role_priority(default: tuple[str, ...], model: dict | None) -> tuple[str, ...]:
    """Roles that clearly help move forward, roles that clearly hurt move back."""
    roles = (model or {}).get("roles") or {}

    def weight(role):
        info = roles.get(role) or {}
        if info.get("decided"):
            return -1 if info.get("lift", 0) > 0 else 1
        return 0
    return tuple(sorted(default, key=lambda r: (weight(r), default.index(r))))


def ask_question(model: dict | None, default: bool) -> bool:
    info = (model or {}).get("question") or {}
    if info.get("decided"):
        return info.get("lift", 0) > 0
    return default


def summary(model: dict | None) -> str:
    """One line for the review mail."""
    model = model or {}
    n = model.get("observations", 0)
    if not n:
        return "Performance: noch keine Plattform-Zahlen"
    parts = [f"Performance aus {n} Post-Messungen"]
    length = model.get("length") or {}
    if length.get("prefer"):
        parts.append(f"Länge: {length['prefer']} besser ({length.get('lift', 0):+.0%})")
    else:
        parts.append(f"Länge: Test läuft ({length.get('n_yes', 0)} kurz / {length.get('n_no', 0)} lang)")
    good = [r for r, i in (model.get("roles") or {}).items() if i.get("decided") and i.get("lift", 0) > 0]
    if good:
        parts.append("stärker mit: " + ", ".join(good))
    return " · ".join(parts)


# ---------------------------------------------------------------- persistence + CLI

def commit_json(path: Path, message: str, *, request=None, retries: int = 4) -> None:
    """Write a data file to main via the contents API (re-read + retry on conflicts)."""
    import requests
    if request is None:
        from .review import github_request as request
    desired = path.read_text(encoding="utf-8")
    for attempt in range(retries):
        sha = None
        try:
            current = request("GET", f"contents/{path.as_posix()}?ref=main")
            sha = current["sha"]
            if base64.b64decode(current["content"]).decode("utf-8") == desired:
                return
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) != 404:
                raise
        body = {"message": message, "branch": "main",
                "content": base64.b64encode(desired.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        try:
            request("PUT", f"contents/{path.as_posix()}", json_body=body)
            return
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) not in (409, 422) or attempt == retries - 1:
                raise
            time.sleep(min(2 ** attempt, 4))


def main() -> int:
    from .state import load_state
    state = load_state()
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"version": 1, "posts": {}}
    try:
        added = collect(state, data)
    except AnalyticsUnavailable as exc:
        print(f"Performance collection skipped: {exc}")
        return 0
    model = build_model(data)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(summary(model))
    if os.getenv("GITHUB_ACTIONS") == "true":
        commit_json(DATA_PATH, f"performance: {added} new analytics snapshots [skip ci]")
        commit_json(MODEL_PATH, "performance: update learned model [skip ci]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
