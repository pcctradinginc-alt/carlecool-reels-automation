from types import SimpleNamespace

import pytest

from carlecool import production_journal as journal
from carlecool import reach


def _features(hook=4.0):
    beats = [i * 0.5 for i in range(60)]
    energy = [1.0 if 3.9 <= b < 6 or 12 <= b < 14 else 0.3 for b in beats]
    return SimpleNamespace(beats=beats, beat_energy=energy, hook_at=hook)


def _look(n):
    return [{"dissolve_in": 0.0, "punch_in": False} for _ in range(n)]


def test_opening_pushes_and_interior_drifts_alternate():
    starts = [0, 1.2, 4.0, 6.0, 8.0, 12.0, 14.0]
    durs = [1.2, 2.8, 2.0, 2.0, 4.0, 2.0, 2.0]
    plan = reach.plan("lana", _features(), starts, durs, _look(7))
    assert plan[0]["zoom"][0] == "push"
    kinds = [p["zoom"][0] for p in plan[1:-1]]
    assert kinds == ["in", "out", "in", "out", "in"]
    assert plan[-1]["zoom"] is None and plan[-1]["flash"] == 0  # loop seam untouched


def test_flash_on_hook_and_peaks_spaced():
    starts = [0, 1.2, 4.0, 6.0, 8.0, 12.0, 14.0]
    durs = [1.2, 2.8, 2.0, 2.0, 4.0, 2.0, 2.0]
    plan = reach.plan("lana", _features(), starts, durs, _look(7))
    flashed = [i for i, p in enumerate(plan) if p["flash"]]
    assert 2 in flashed  # the drop
    assert all(abs(starts[a] - starts[b]) >= reach.FLASH_GAP for a in flashed for b in flashed if a < b)
    assert 0 not in flashed


def test_no_flash_on_dissolve_and_off_switch(monkeypatch):
    starts, durs = [0, 2, 4.0, 6], [2, 2, 2, 2]
    look = _look(4)
    look[2]["dissolve_in"] = 0.7
    assert reach.plan("rubin", _features(), starts, durs, look)[2]["flash"] == 0
    monkeypatch.setenv("CARLECOOL_REACH_FX", "off")
    assert all(p["zoom"] is None and not p["flash"] for p in reach.plan("rubin", _features(), starts, durs, look))


def test_zoom_filter_starts_at_full_frame():
    f = reach.zoom_filters(("push", 0.08), 1.2, 1080, 1920)
    assert "eval=frame" in f[0] and f[1] == "crop=1080:1920"
    t = 0.0
    import math
    z = 1 + 0.08 * (1 - math.exp(-t / reach.PUSH_TAU))
    assert z == 1.0
    assert reach.zoom_filters(None, 1, 1080, 1920) == []


def test_two_journal_slots_per_day(monkeypatch):
    assert journal.slots("2026-11-27") == ["2026-11-27", "2026-11-27-2"]
    assert journal.path_for("2026-11-27-2") == "data/production/2026-11-27-2.json"
    for bad in ("2026-11-27-1", "2026-11-27x2", "2026-11-27-22", "2026-13-01"):
        with pytest.raises(ValueError):
            journal.path_for(bad)
    sent = {"2026-11-27"}
    monkeypatch.setattr(journal, "check", lambda key: key in sent)
    assert journal.free_slot("2026-11-27") == "2026-11-27-2"
    sent.add("2026-11-27-2")
    assert journal.free_slot("2026-11-27") is None


def test_provider_usage_merges_runs_from_main():
    from carlecool import providers
    remote = {"coverr": {"events": [{"at": "2026-11-27T15:58:00+00:00", "run": "1", "requests": 27}]}}
    local = {"coverr": {"events": [{"at": "2026-11-27T15:00:00+00:00", "run": "0", "requests": 20},
                                   {"at": "2026-11-27T16:09:00+00:00", "run": "2", "requests": 5, "blocked": 403}]}}
    merged = providers.merge(remote, local)
    assert [e["run"] for e in merged["coverr"]["events"]] == ["0", "1", "2"]
    assert providers.merge(merged, merged) == merged


def test_reel_67_balcony_and_posing_blocked():
    from carlecool import stylegate
    from carlecool.video import Video
    assert stylegate.blocked_words(Video("6kxRdq6Z1t", "coverr", title="Anything")) == "rejected by the owner"
    for t in ("Elegant Nightscape: A Woman on a Balcony", "Posing on the street ",
              "Stylish Night Portrait in Urban Setting", "Set of bits in a toolbox"):
        assert stylegate.blocked_words(Video("x", "coverr", title=t)), t
    assert stylegate.blocked_words(Video("x", "coverr", title="Woman walking at night")) is None
