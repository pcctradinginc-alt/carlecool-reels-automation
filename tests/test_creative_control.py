"""CarleCool creative inputs are real, bounded, deterministic and owner-controlled."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from carlecool.creative import (
    CUES, DEFAULT_WEIGHTS, PRESETS, apply_commands, choose_shots,
    default_profile, interpret_revision, load_profile, validate_profile,
)


def test_all_presets_have_proportional_integer_weights():
    assert DEFAULT_WEIGHTS == {"nature": 28, "studio": 22, "americana": 20,
                               "skate": 18, "y2k": 7, "night": 5}
    for name, weights in PRESETS.items():
        p = apply_commands(default_profile(), ["preset_" + name])
        assert p["preset"] == name
        assert sum(p["weights"].values()) == 100
        assert all(v >= 0 for v in p["weights"].values())


def test_artist_feedback_changes_actual_query_pool_and_pace():
    first = default_profile()
    updated = apply_commands(first, ["more_nature", "less_skate", "more_analog",
                                     "slower_cuts", "first_30_seconds"])
    assert updated["weights"]["nature"] > first["weights"]["nature"]
    assert updated["weights"]["skate"] < first["weights"]["skate"]
    assert updated["analog"] > first["analog"]
    assert updated["pace"] == "slow"
    assert updated["music"] == "beginning"
    assert sum(updated["weights"].values()) == 100
    assert first["weights"] == DEFAULT_WEIGHTS  # no mutation


def test_short_and_german_free_text_commands():
    assert interpret_revision("/revise preset_rubin_lana") == ["preset_rubin_lana"]
    assert interpret_revision("/revise more_mpc") == ["more_mpc"]
    assert interpret_revision("/revise mehr natur, weniger skate") == ["more_nature", "less_skate"]
    assert interpret_revision("/revise mehr studio, mehr palmen und ruhigere schnitte") == [
        "more_studio", "more_palm_sunset", "slower_cuts"
    ]
    for bad in ("/publish", "/revise rm -rf everything",
                "/revise " + ("a" * 501), "/revise hacker\ninjection"):
        with pytest.raises(ValueError):
            interpret_revision(bad)


def test_queries_are_seeded_distinct_lanes_from_explicit_style():
    p = default_profile()
    sample = choose_shots(p, track_id="123", mood="cinematic", energy=.5)
    assert sample == choose_shots(p, track_id="123", mood="cinematic", energy=.5)
    assert len(sample) == len(set(sample)) == 3
    assert all(any(phrase in lane for lane in CUES.values()) for phrase in sample)
    p["revision"] = 1
    changed = choose_shots(p, track_id="123", mood="cinematic", energy=.5)
    assert len(changed) == 3
    assert sum(p["weights"].values()) == 100


def test_style_validation_rejects_untrusted_options():
    bad = default_profile()
    bad["weights"]["night"] = -1
    with pytest.raises(ValueError):
        validate_profile(bad)
    bad = default_profile()
    bad["pace"] = "ffmpeg-injection"
    with pytest.raises(ValueError):
        validate_profile(bad)
    bad = default_profile()
    bad["analog"] = 900
    with pytest.raises(ValueError):
        validate_profile(bad)
    with pytest.raises(ValueError):
        apply_commands(default_profile(), ["unauthorized"])


def test_profile_file_is_readable_and_valid():
    path = Path("data/creative-profile.json")
    profile = load_profile(path)
    assert profile["preset"] == "rubin_analog_lana_skate"
    assert sum(profile["weights"].values()) == 100
