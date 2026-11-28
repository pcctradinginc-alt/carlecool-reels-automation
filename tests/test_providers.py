"""Coverr's hourly limit across runs (26 Nov: five runs in a row hit HTTP 403)."""
from datetime import datetime, timedelta, timezone

from carlecool import providers

NOW = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)


def _data(*events):
    return {"coverr": {"events": [{"at": (NOW - timedelta(minutes=m)).isoformat(), "requests": r, "blocked": b}
                                  for m, r, b in events]}}


def test_fresh_hour_goes_with_capped_budget():
    plan = providers.coverr_plan(_data((90, 35, None)), NOW)          # older than an hour
    L = providers.HOURLY_LIMIT
    assert plan["action"] == "go" and plan["budget"] == L - 2
    plan = providers.coverr_plan(_data((20, 15, None)), NOW)
    assert plan["action"] == "go" and plan["budget"] == L - 15 - 2


def test_recent_block_or_spent_hour_waits_then_skips():
    plan = providers.coverr_plan(_data((40, 30, 403)), NOW)          # blocked 40 min ago
    assert plan["action"] == "wait" and 20 * 60 <= plan["wait_s"] <= 21 * 60
    plan = providers.coverr_plan(_data((10, 35, None)), NOW)          # 35 used 10 min ago
    assert plan["action"] == "wait" and 50 * 60 <= plan["wait_s"] <= 51 * 60   # ≤ 60 min: wait
    plan = providers.coverr_plan(_data((0, 20, 403)), NOW)            # blocked just now: 60 min
    assert plan["action"] == "wait"
    plan = providers.coverr_plan(_data((50, 35, None)), NOW)
    assert plan["action"] == "wait" and plan["wait_s"] <= 11 * 60


def test_record_keeps_two_days(tmp_path):
    path = tmp_path / "usage.json"
    providers.record(12, None, "1", path, NOW - timedelta(days=3))
    data = providers.record(30, 403, "2", path, NOW)
    assert [e["run"] for e in data["coverr"]["events"]] == ["2"]
    assert providers.coverr_plan(data, NOW + timedelta(minutes=5))["action"] in ("wait", "skip")


def test_main_applies_the_plan(monkeypatch):
    from carlecool import main, video
    waited = []
    monkeypatch.setattr(providers, "coverr_plan", lambda: {"action": "wait", "budget": 45, "wait_s": 600, "reason": "t"})
    monkeypatch.setattr(video, "COVERR_MAX_REQUESTS", 35)
    main.apply_coverr_plan(sleep=waited.append)
    assert waited == [600] and video.COVERR_MAX_REQUESTS == 35
    monkeypatch.setattr(providers, "coverr_plan", lambda: {"action": "skip", "budget": 0, "wait_s": 0, "reason": "t"})
    monkeypatch.setitem(video.COVERR_BLOCK, "status", None)
    main.apply_coverr_plan(sleep=waited.append)
    assert video.coverr_blocked() == 429
    monkeypatch.setitem(video.COVERR_BLOCK, "status", None)


def test_budget_after_waiting_counts_what_is_still_in_the_hour():
    # 30 requests 50 min ago and 30 requests 20 min ago: waiting 10 min frees only the first 30
    plan = providers.coverr_plan(_data((50, 30, None), (20, 30, None)), NOW)
    L = providers.HOURLY_LIMIT
    assert plan["action"] == "wait" and plan["budget"] == L - 2         # waits until both are out
    plan = providers.coverr_plan(_data((50, 30, None), (40, 10, None)), NOW)
    assert plan["action"] == "wait" and plan["budget"] == L - 10 - 2
