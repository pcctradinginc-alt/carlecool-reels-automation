"""Owner, 28 Nov: try different parts of each song and compare in the evaluation."""
import numpy as np

from carlecool import analysis, performance


def test_each_song_gets_every_part_in_turn(monkeypatch):
    monkeypatch.delenv("CARLECOOL_EXCERPT", raising=False)
    hist, seen = [], []
    for k in range(3):
        e = performance.choose_excerpt("t1", hist, f"r{k}")["excerpt"]
        seen.append(e)
        hist.append({"track_id": "t1", "excerpt": e})
    assert sorted(seen) == sorted(analysis.EXCERPTS)
    assert performance.choose_excerpt("t2", hist, "x")["excerpt"] in analysis.EXCERPTS  # other song: own rotation
    monkeypatch.setenv("CARLECOOL_EXCERPT", "start")
    assert performance.choose_excerpt("t1", hist, "x") == {"excerpt": "start", "reason": "manual"}


def test_second_part_is_another_strong_lift_far_from_the_hook():
    beats = np.arange(0, 120, 0.5)
    energy = np.full(len(beats), 0.2)
    energy[(beats >= 30) & (beats < 50)] = 1.0     # the hook (biggest lift)
    energy[(beats >= 80) & (beats < 100)] = 0.8    # another strong part
    downs = list(range(0, len(beats), 4))
    hook, _ = analysis._hook_start(beats, downs, energy, 18.0, 120.0)
    second, _ = analysis._hook_start(beats, downs, energy, 18.0, 120.0, excerpt="second")
    assert abs(hook - 30) <= 2 and abs(second - hook) >= 0.75 * 18 and 76 <= second <= 82


def test_excerpt_is_a_reported_factor():
    rows = [{"relative": 1.0, "facts": {"excerpt": e}} for e in ("hook", "second", "start", "hook")]
    rep = performance._model_for(rows)["report"]["excerpt"]
    assert rep["hook"]["n"] == 2 and rep["hook"]["enough"] is False
