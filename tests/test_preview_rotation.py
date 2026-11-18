"""Regression tests: fair daily random songs and durable private preview tracking."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from random import Random

import pytest

from carlecool.creative import default_profile, choose_shots
from carlecool.history import (
    load_preview_history, pick_preview_track, recent_video_ids,
    record_preview_delivery,
)
from carlecool.soundcloud import Track


def tracks(n=20):
    return [Track(id=str(i), title=f"Song {i}", permalink_url=f"https://soundcloud.com/carlecool/{i}")
            for i in range(n)]


def test_each_of_20_tracks_used_once_before_repetition():
    catalog = tracks()
    history = []
    counts = Counter()
    rng = Random(4720)
    for i in range(100):
        song = pick_preview_track(catalog, history, rng=rng)
        counts[song.id] += 1
        history.append({"track_id": song.id, "kind": "daily"})
        assert max(counts[t.id] for t in catalog) - min(counts[t.id] for t in catalog) <= 1
    assert set(counts) == {t.id for t in catalog}
    assert set(counts.values()) == {5}


def test_fairness_for_rolling_20_with_new_song():
    catalog = tracks(20)
    old = [{"track_id": str(i), "kind": "daily"} for i in range(20)]
    latest = [Track(id="new", title="New", permalink_url="")] + catalog[1:]
    assert pick_preview_track(latest, old, rng=Random(1)).id == "new"


def test_revisions_do_not_inflate_song_counts():
    catalog = tracks(2)
    history = [
        {"kind": "daily", "track_id": "0"},
        {"kind": "revision", "track_id": "0"},
        {"kind": "revision", "track_id": "0"},
    ]
    assert pick_preview_track(catalog, history, rng=Random(1)).id == "1"


def test_random_choice_within_least_used_pool():
    catalog = tracks(20)
    a = [pick_preview_track(catalog, [], rng=Random(seed)).id for seed in range(20)]
    assert len(set(a)) > 2


def test_recent_stock_avoidance_and_run_seed_variation():
    history = [
        {"video_ids": ["A", "B", "hf-ltx23-1"]},
        {"video_ids": ["B", "C"]},
    ]
    assert recent_video_ids(history) == {"A", "B", "C"}
    base = default_profile()
    seed_results = [
        tuple(choose_shots(base, track_id="23", mood="cinematic", energy=.2, run_key=str(i)))
        for i in range(10)
    ]
    assert len(set(seed_results)) > 3
    assert tuple(choose_shots(base, track_id="23", mood="cinematic", energy=.2, run_key="1")) == seed_results[1]


def test_history_fails_closed_when_missing_or_invalid(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        load_preview_history(missing)
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"version": 1, "previews": "oops"}', encoding="utf-8")
    with pytest.raises(ValueError, match="history"):
        load_preview_history(invalid)


def test_github_history_recording_idempotent(monkeypatch):
    import base64
    import json
    from unittest.mock import patch

    server = {"version": 1, "previews": []}
    state = {"sha": "first", "writes": 0}

    def fake_request(method, path, **kw):
        assert kw["repo"] == "owner/repo"
        if method == "GET":
            return {"sha": state["sha"],
                    "content": base64.b64encode(json.dumps(server).encode()).decode()}
        if method == "PUT":
            data = kw["json_body"]
            assert data["sha"] == state["sha"]
            server.update(json.loads(base64.b64decode(data["content"])))
            state["sha"] = "second"
            state["writes"] += 1
            return {}
        raise AssertionError(method)

    meta = {"track_id": "8", "video_ids": ["coverr-1"], "sha256": "test-hash"}
    with patch("carlecool.review.github_request", side_effect=fake_request):
        assert record_preview_delivery(meta, run_id=123, kind="daily",
                                       token="fake", repo="owner/repo")
        assert not record_preview_delivery(meta, run_id=123, kind="daily",
                                           token="fake", repo="owner/repo")
    assert state["writes"] == 1
    assert server["previews"][0]["track_id"] == "8"
