"""Performance learning from REAL platform numbers (Zernio analytics).

1. Collect (daily workflow `performance.yml`): for every Reel published via Zernio
   (data/state.json → provider_post_id) the post metrics are fetched at three
   checkpoints — 2, 7 and 28 days after publishing — with GET /v1/analytics?postId=…
   and stored in data/performance.json (views, shares, saves, comments, likes, average
   watch time, completion rate, replays — whatever the platform returns).
2. Score (owner goal 25 Nov: maximum views for song promotion): per post and platform,
   five parts, each relative to the median of the owner's own posts on that platform:
   reach (views) 30 %, watch time ÷ video length 25 %, completion rate 20 %,
   shares + saves + reposts per view 20 %, likes + comments per view 5 %. These are our
   own optimisation weights, not TikTok's. Missing values are left out (never counted
   as zero); watch time units are checked against the video length.
3. Learn (data/performance-model.json): one model PER PLATFORM (TikTok and Instagram
   react differently); main.py follows the TikTok model (the Reels' main target).
   Variants are compared only when BOTH sides have at least MIN_POSTS posts and differ by
   at least MIN_LIFT. Learned:
     * Reel length (short ≈15–20 s vs long ≈24–30 s) → used by the length test,
     * signature roles (gear, friends, flag, car …) → placement priority,
     * caption question yes/no → how often a question is asked,
     * on-screen text hook yes/no (hooktext.py) → how often a line is shown.
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
CHECKPOINTS = (("d1", 1), ("d2", 2), ("d7", 7), ("d28", 28))  # d1 = early indicator (25 Nov)
PRIMARY_PLATFORM = "tiktok"
PART_CAP = 3.0  # a score part counts at most 3x the platform median
WEIGHTS = {"reach": 0.30, "watch": 0.25, "completion": 0.20, "share": 0.20, "like": 0.05}
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
    latest_done = max((days for name, days in CHECKPOINTS if name in done), default=0)
    due = [(name, days) for name, days in CHECKPOINTS
           if name not in done and days > latest_done and now - at >= timedelta(days=days)]
    # A checkpoint long overdue (e.g. analytics were down) would get TODAY's numbers and
    # fake the growth curve: only the latest due checkpoint is filled then, older missed
    # ones are skipped (25 Nov).
    age_days = (now - at).total_seconds() / 86400
    fair = [n for n, d in due if age_days <= d * 1.5 + 1]
    return fair or ([due[-1][0]] if due else [])


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
            fetched = now or datetime.now(timezone.utc)
            try:
                age_h = round((fetched - datetime.fromisoformat(str(record.get("at")))).total_seconds() / 3600, 1)
            except (TypeError, ValueError):
                age_h = None
            entry["checkpoints"][name] = {"fetched": fetched.isoformat(timespec="seconds"),
                                          "age_hours": age_h, "platforms": metrics}
            added += 1
            print(f"Analytics {post_id} {name}: " + ", ".join(
                f"{p}: {int(m.get('views', 0))} views, {int(m.get('shares', 0))} shares"
                for p, m in metrics.items()))
    data["updated"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return added


# ---------------------------------------------------------------- scoring + model

def _num(metrics: dict, key: str) -> float | None:
    value = metrics.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def watch_seconds(metrics: dict) -> float | None:
    """Average watch time in seconds. Zernio reports TikTok and Instagram in ms (2480 for a
    12.6 s video); a value that cannot be seconds (more than 3× the video) is ms."""
    avg, length = _num(metrics, "igReelsAvgWatchTime"), _num(metrics, "videoDurationSeconds")
    if avg is None or avg <= 0:
        return None
    if length and avg > 3 * length:
        return avg / 1000.0
    return avg if length else (avg / 1000.0 if avg > 100 else avg)


def components(metrics: dict) -> dict[str, float] | None:
    """Raw score parts of one post; None below 20 views. Missing parts are absent."""
    views = _num(metrics, "views") or _num(metrics, "impressions") or 0.0
    if views < 20:
        return None
    out = {"reach": views}
    watch, length = watch_seconds(metrics), _num(metrics, "videoDurationSeconds")
    if watch is not None and length:
        out["watch"] = min(2.0, watch / max(1.0, length))
    completion = _num(metrics, "completionRate")
    if completion is not None:
        out["completion"] = completion / 100.0 if completion > 1 else completion
    shares = [_num(metrics, k) for k in ("shares", "saves", "reposts")]
    if any(v is not None for v in shares):
        out["share"] = sum(v or 0.0 for v in shares) / views
    likes = [_num(metrics, k) for k in ("likes", "comments")]
    if any(v is not None for v in likes):
        out["like"] = sum(v or 0.0 for v in likes) / views
    return out


def post_score(metrics: dict) -> float | None:
    """Absolute weighted score of one post (kept for reports; learning uses relative scores)."""
    parts = components(metrics)
    if parts is None:
        return None
    return sum(WEIGHTS[k] * v for k, v in parts.items() if k != "reach") + WEIGHTS["reach"] * (parts["reach"] / 1000.0)


def _latest(entry: dict) -> dict:
    for name in ("d28", "d7", "d2"):
        if name in entry.get("checkpoints", {}):
            return entry["checkpoints"][name]["platforms"]
    return {}


def observations(data: dict) -> list[dict]:
    """One row per (post, platform). `relative` = weighted mean of each score part divided
    by that platform's median of the part (1.0 = a typical post of the owner)."""
    rows = []
    for post_id, entry in (data.get("posts") or {}).items():
        for platform, metrics in _latest(entry).items():
            if platform == "all":
                continue
            parts = components(metrics)
            if parts is not None:
                rows.append({"post": post_id, "platform": platform, "parts": parts,
                             "score": post_score(metrics), "facts": entry.get("facts") or {}})
    for platform in {r["platform"] for r in rows}:
        mine = [r for r in rows if r["platform"] == platform]
        stats = {}
        for key in WEIGHTS:
            vals = [r["parts"][key] for r in mine if key in r["parts"]]
            if vals:
                mean = sum(vals) / len(vals)
                stats[key] = (statistics.median(vals), 0.25 * mean if mean > 0 else 1.0)
        for r in mine:
            num = den = 0.0
            for key, value in r["parts"].items():
                median, smooth = stats[key]
                # capped: one share against a median of 0 must not make a post "6.5x" (25 Nov)
                num += WEIGHTS[key] * min(PART_CAP, (value + smooth) / (median + smooth))
                den += WEIGHTS[key]
            r["relative"] = round(num / den, 4) if den else 1.0
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
    """Model for the primary platform (TikTok) on top, every platform separately inside."""
    rows = observations(data)
    per_platform = {p: _model_for([r for r in rows if r["platform"] == p])
                    for p in sorted({r["platform"] for r in rows})}
    primary = PRIMARY_PLATFORM if PRIMARY_PLATFORM in per_platform else (next(iter(per_platform), None))
    model = dict(per_platform.get(primary) or _model_for([]))
    model.update({"version": 2, "platform": primary, "platforms": per_platform,
                  "observations_all": len(rows)})
    return model


def _model_for(rows: list[dict]) -> dict:
    model = {"observations": len(rows), "min_posts": MIN_POSTS, "min_lift": MIN_LIFT,
             "length": None, "roles": {}, "question": None, "text": None, "styles": {}}
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
    text = _compare(rows, lambda f: None if "text_hook" not in f else bool(f["text_hook"]))
    if text:
        model["text"] = dict(text, prefer=("text" if text.get("lift", 0) > 0 else "none")
                             if text.get("decided") else None)
    for world in ("lana", "rubin", "night"):  # report only
        vals = [r["relative"] for r in rows
                if (("night" if r["facts"].get("variant") == "night" else r["facts"].get("style")) == world)]
        if vals:
            model["styles"][world] = {"n": len(vals), "median_relative": round(statistics.median(vals), 3)}
    return model


def load_model(path: Path = MODEL_PATH) -> dict:
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
        return model if isinstance(model, dict) and model.get("version") in (1, 2) else {}
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


def preferred(model: dict | None, key: str) -> str | None:
    """Learned winner of an A/B test ("text" / "none" for the text hook), else None."""
    return ((model or {}).get(key) or {}).get("prefer")


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
    platform = model.get("platform")
    parts = [f"Performance aus {n} Post-Messungen" + (f" ({platform})" if platform else "")]
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
