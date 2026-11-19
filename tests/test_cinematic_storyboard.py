"""Offline regression tests for music-aware montage; no account/API access."""
import math
import pytest

from carlecool.analysis import AudioFeatures
from carlecool.cinematic import build_storyboard, plan_cuts


@pytest.mark.parametrize("pace", ["slow", "medium", "fast"])
def test_cut_plan_exact_length_and_positive_shots(pace):
    durations = plan_cuts(30.0, 117.0, pace=pace, beat_phase=0.28)
    assert all(x >= 1.0 for x in durations)
    assert math.isclose(sum(durations), 30.0, abs_tol=0.001)
    assert len(durations) >= 2


def test_cut_plan_sanitizes_unknown_bpm_and_phase():
    durations = plan_cuts(20.0, float("nan"), beat_phase=float("nan"))
    assert math.isclose(sum(durations), 20.0, abs_tol=0.001)


def test_storyboard_uses_offsets_and_avoids_immediate_repetition():
    durations = plan_cuts(30, 128, pace="fast", beat_phase=0.3)
    shots = build_storyboard(durations, [9.0, 6.0, 7.0], seed="test")
    assert len(shots) == len(durations)
    assert any(shot.source_offset > 0 for shot in shots[3:])
    assert all(shot.source_offset >= 0 for shot in shots)
    assert all(shots[i].source_index != shots[i - 1].source_index
               for i in range(1, len(shots)))
    assert shots == build_storyboard(durations, [9.0, 6.0, 7.0], seed="test")


def test_one_source_still_valid():
    shots = build_storyboard([4.0] * 5, [5.0], seed="single")
    assert len(shots) == 5
    assert all(s.source_index == 0 and s.source_offset <= 1.0 for s in shots)


def test_invalid_inputs_fail_closed():
    with pytest.raises(ValueError):
        plan_cuts(30, 120, pace="insane")
    with pytest.raises(ValueError):
        plan_cuts(-1, 120)
    with pytest.raises(ValueError):
        build_storyboard([2], [0])


def test_audiofeature_legacy_constructor():
    features = AudioFeatures(120.0, .5, 4.0, "calm", 100.0)
    assert features.beat_phase == 0.0
