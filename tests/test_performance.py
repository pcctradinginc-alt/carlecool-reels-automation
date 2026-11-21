"""Captions, length A/B test, analytics collection and the learned model."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from carlecool import captions, performance
from carlecool.approve import validate_footage_rights
from carlecool.main import caption_for
from carlecool.video import Video


def test_caption_has_search_line_niche_tags_and_keeps_every_credit():
    track = SimpleNamespace(title="chronocyte horizon")
    clips = [Video("a", "coverr", creator_name="Jane", creator_url="https://coverr.co/jane"),
             Video("pl-x", "prelinger")]
    copy = captions.variant("rubin", None, "run-1")
    text = caption_for(track, clips, copy)
    lines = text.splitlines()
    assert lines[0] == "🎧 carl e cool - chronocyte horizon"
    assert lines[1] in captions.SEARCH_LINES["rubin"]
    assert lines[-1].split()[0] == "#carlecool" and 4 <= len(lines[-1].split()) <= 5
    assert "#rap" not in text
    validate_footage_rights({"caption": text, "footage_sources": [{"provider": "coverr"}, {"provider": "prelinger"}]})


def test_question_appears_on_about_every_third_reel():
    asked = sum(bool(captions.variant("lana", None, f"run-{i}")["question"]) for i in range(300))
    assert 70 < asked < 130


def test_length_test_alternates_per_song_and_follows_a_learned_winner(monkeypatch):
    monkeypatch.delenv("CARLECOOL_LENGTH_TEST", raising=False)
    prev = [{"track_id": "1", "length_bucket": "long"}, {"track_id": "2", "length_bucket": "short"}]
    assert performance.choose_length("1", prev, 30, "r")["bucket"] == "short"
    assert performance.choose_length("1", prev, 30, "r")["target"] == 12.0
    prev.append({"track_id": "1", "length_bucket": "short"})
    prev.append({"track_id": "1", "length_bucket": "short"})
    assert performance.choose_length("1", prev, 30, "r")["bucket"] == "long"
    model = {"length": {"prefer": "short"}}
    picks = [performance.choose_length("1", prev, 30, f"r{i}", model)["bucket"] for i in range(200)]
    assert 0.6 < picks.count("short") / 200 < 0.8
    monkeypatch.setenv("CARLECOOL_LENGTH_TEST", "off")
    assert performance.choose_length("1", prev, 30, "r", model)["bucket"] == "long"


def test_collect_fetches_checkpoints_once_and_parses_platforms():
    now = datetime(2026, 12, 20, tzinfo=timezone.utc)
    state = {"published": [
        {"provider": "zernio", "provider_post_id": "p1", "track_id": "1",
         "at": (now - timedelta(days=8)).isoformat(), "reel_facts": {"length_bucket": "short"}},
        {"provider": "zernio", "provider_post_id": "p2", "at": (now - timedelta(hours=20)).isoformat()},
        {"instagram_media_id": "x", "at": (now - timedelta(days=30)).isoformat()}]}
    payload = {"post": {"platformAnalytics": [
        {"platform": "tiktok", "platformPostUrl": "https://tiktok.com/x",
         "analytics": {"views": 1000, "shares": 12, "saves": 8, "likes": 90, "comments": 4, "completionRate": 31.5}}]}}
    calls = []

    def fetch(post_id):
        calls.append(post_id)
        return performance.parse_analytics(payload)

    data = {"posts": {}}
    assert performance.collect(state, data, fetch=fetch, now=now) == 2   # d2 + d7 for p1
    assert calls == ["p1", "p1"]
    assert data["posts"]["p1"]["checkpoints"]["d7"]["platforms"]["tiktok"]["shares"] == 12
    assert performance.collect(state, data, fetch=fetch, now=now) == 0   # nothing due again
    assert data["posts"]["p1"]["facts"] == {"length_bucket": "short"}


def test_model_needs_enough_posts_before_deciding():
    def post(bucket, shares, roles=("gear",)):
        return {"facts": {"length_bucket": bucket, "roles": list(roles), "question": False, "style": "lana"},
                "checkpoints": {"d7": {"platforms": {"tiktok": {"views": 1000, "shares": shares, "likes": 50}}}}}
    data = {"posts": {f"s{i}": post("short", 30) for i in range(3)} | {f"l{i}": post("long", 10, ()) for i in range(4)}}
    model = performance.build_model(data)
    assert model["length"]["decided"] is False and model["length"]["prefer"] is None   # only 3 short
    data["posts"]["s3"] = post("short", 30)
    model = performance.build_model(data)
    assert model["length"]["prefer"] == "short" and model["roles"]["gear"]["decided"]
    assert performance.role_priority(("skater", "friends", "gear"), model)[0] == "gear"
    assert "Länge: short besser" in performance.summary(model)
    assert performance.role_priority(("skater", "gear"), {}) == ("skater", "gear")


def test_tiny_or_missing_numbers_are_ignored():
    assert performance.post_score({"views": 5, "shares": 3}) is None
    assert performance.parse_analytics({}) == {}
    assert performance.due_checkpoints("not a date", {}) == []
