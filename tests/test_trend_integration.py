"""Viral Intelligence Engine (owner, 28 Nov): scout, compatibility, vetoes, 70/20/10, shadow mode."""
from datetime import date

from carlecool import trend_compatibility as tc, trend_intelligence as ti

TREND = {"id": "x", "name": "Analog Loop", "category": "editing", "mechanism": "hands on a turntable",
         "keywords": ["vinyl"], "music": {"drive": "groove"}, "momentum": 0.6, "rights_ok": True,
         "evidence": {"verified": False, "noted": "2026-11-28"}, "expires": "2027-02-28",
         "translations": {"lana": {"themes": ["studio"], "text": "pov: the sample that started it"}}}


def test_registry_entries_are_mechanisms_with_evidence_and_expiry():
    trends = ti.load()
    assert trends and all(t["category"] in ti.CATEGORIES and t.get("expires") and "evidence" in t for t in trends)
    assert all(t["evidence"]["verified"] is False for t in trends)  # nothing invented as "viral"
    assert ti.active([dict(TREND, expires="2020-01-01")], date(2026, 11, 28)) == []
    assert ti.momentum(TREND, ["vinyl"]) == 0.7 and ti.evidence_quality(TREND) == "unverified"


def test_compatibility_score_and_hard_vetoes():
    ok = tc.score(TREND, director="lana", theme="studio", music_classes={"drive": "groove"}, exclusions=[], recent_ids=[])
    assert ok["veto"] is None and ok["score"] >= tc.THRESHOLD and ok["adaptation"]["text"].startswith("pov")
    assert tc.score(TREND, director="night", theme="studio", music_classes={}, exclusions=[], recent_ids=[])["veto"]
    assert tc.score(dict(TREND, rights_ok=False), director="lana", theme="studio", music_classes={},
                    exclusions=[], recent_ids=[])["veto"] == "unclear usage rights"
    assert tc.score(TREND, director="lana", theme="studio", music_classes={"drive": "sparse"},
                    exclusions=[], recent_ids=[])["veto"] == "the song does not fit the mechanism"
    off_theme = tc.score(TREND, director="lana", theme="hamptons", music_classes={"drive": "groove"},
                         exclusions=[], recent_ids=[])
    assert off_theme["score"] < ok["score"]


def test_70_20_10_buckets_and_no_trend_is_valid(monkeypatch):
    hist, seen = [], []
    for k in range(20):
        b = tc.bucket(hist, f"r{k}")
        seen.append(b)
        hist.append({"trend_bucket": b})
    assert seen.count("signature") == 14 and seen.count("trend") == 4 and seen.count("experiment") == 2
    monkeypatch.delenv("CARLECOOL_TREND_MODE", raising=False)
    d = tc.decide(director="lana", theme="minimal", music_classes={"drive": "sparse"},
                  previews=[{"trend_bucket": "signature"}] * 7, run_key="x", trends=[TREND])
    assert d["mode"] == "shadow" and d["bucket"] in ("trend", "experiment") and d["chosen"] is None
    assert d["note"] == "no suitable trend (a valid result)"
