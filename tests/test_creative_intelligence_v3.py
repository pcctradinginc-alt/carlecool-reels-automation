"""Regression coverage for optional creative intelligence. No paid or private APIs."""
from datetime import datetime, timezone
from email.utils import format_datetime
import json
import numpy as np
import pytest

from carlecool.music_structure import detect_structure, align_to_structure
from carlecool.quality_learning import initial, observe, adjusted_weights, validate
from carlecool.trend_signals import parse_feed, apply_trend, fetch_signals, RSS
from carlecool.semantic import score_semantic


def test_structure_is_relative_and_bounded():
    sr = 800
    rng = np.random.default_rng(2)
    signal = rng.normal(0, .008, sr * 20).astype(np.float32)
    signal[sr * 9:sr * 12] += rng.normal(0, .25, sr * 3).astype(np.float32)
    signals = detect_structure(signal, sr)
    assert all(0 < t < 20 for t in signals)
    assert tuple(sorted(signals)) == signals
    assert len(signals) <= 12


def test_structure_silence_and_short_audio():
    assert detect_structure(np.zeros(8000), 800) == ()
    assert detect_structure(np.zeros(100), 800) == ()


def test_structure_snap_preserves_total():
    original = [4., 4., 4., 4.]
    values = align_to_structure(original, (4.4, 12.2))
    assert abs(sum(values) - 16) < .001
    assert all(v >= 1. for v in values)
    assert abs(values[0] - 4.4) < .001
    assert align_to_structure(original, ()) == original


def test_revision_learning_is_explicit_bounded():
    data = initial()
    for _ in range(30):
        data = observe(data, ["more_nature", "less_skate", "nonsense"])
    assert data["preferences"]["nature"] == 8
    assert data["preferences"]["skate"] == -8
    assert data["observations"] == 30
    weights = adjusted_weights({k: 10 for k in data["preferences"]}, data)
    assert weights["nature"] == 18 and weights["skate"] == 2
    assert observe(data, ["slower_cuts"])["observations"] == 30
    with pytest.raises(ValueError):
        validate({"version": 1, "observations": 0, "preferences": {"nature": 100}})


def test_trend_feed_freshness_and_irrelevance():
    now = datetime(2026, 11, 19, 18, tzinfo=timezone.utc)
    stamp = format_datetime(now)
    xml = f"<rss><channel><item><title>vintage photography</title><pubDate>{stamp}</pubDate></item><item><title>football championship</title><pubDate>{stamp}</pubDate></item></channel></rss>"
    assert parse_feed(xml.encode(), now=now) == ["vintage"]
    assert parse_feed(b"<rss><channel/></rss>", now=now) == []
    assert apply_trend(["nature", "city", "music"], {"status": "ok", "topics": ["vintage"]})[-1] == "vintage roadside motel dusk"
    assert apply_trend(["a","b","c"], {"status": "unavailable", "topics": []}) == ["a","b","c"]


def test_trend_never_calls_arbitrary_host():
    class FakeResponse:
        status_code = 200
        content = b"<rss><channel/></rss>"
    class FakeSession:
        def get(self, url, **kwargs):
            assert url == RSS and kwargs["allow_redirects"] is False
            return FakeResponse()
    assert fetch_signals(session=FakeSession())["status"] == "ok"


def test_semantic_feature_fails_closed_without_usable_media(tmp_path):
    assert score_semantic(tmp_path / "missing", []) is None
    # Runtime may or may not have optional OpenCLIP installed; no network is
    # attempted because the missing cover causes video frame extraction to fail
    # before any rank can be returned when a mock is injected.
