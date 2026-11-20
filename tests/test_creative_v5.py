"""Creative v5 is free, strictly optional and cannot post any video."""
import pytest

from carlecool.creative_v5 import (
    ROLE_QUERIES, choose_verified_roles, direction_from_scores, enabled,
    is_role_candidate, prioritize_candidates, search_phrases,
)
from carlecool.cinematic import build_storyboard
from carlecool.video import Video, query_ladder


def test_classic_default_unmodified(monkeypatch):
    monkeypatch.delenv("CARLECOOL_CREATIVE_V5", raising=False)
    assert not enabled()
    monkeypatch.setenv("CARLECOOL_CREATIVE_V5", "on")
    assert enabled()
    monkeypatch.setenv("CARLECOOL_CREATIVE_V5", "off")
    assert not enabled()


def test_horse_and_flag_trigger_americana():
    plan = direction_from_scores(
        {"americana": 0.33, "pastel_cosmos": 0.16, "night_city": 0.17},
        {"brightness": 0.6, "saturation": 0.3, "warmth": 0.08, "greenness": 0},
    )
    assert plan["style"] == "americana"
    assert plan["basis"] == "openclip"
    assert "road" in plan["cover_query"]


def test_pastel_planet_triggers_cosmic_world():
    plan = direction_from_scores(
        {"pastel_cosmos": 0.34, "americana": 0.11, "coastal_zen": 0.19},
        {"brightness": 0.7, "saturation": 0.12, "warmth": 0, "greenness": 0},
    )
    assert plan["style"] == "pastel_cosmos"
    assert plan["cover_query"] == "pastel clouds sky"


def test_ambiguous_motifs_fall_back_to_existing_palette():
    plan = direction_from_scores(
        {"pastel_cosmos": 0.235, "americana": 0.23},
        {"brightness": 0.7, "saturation": 0.12, "warmth": 0, "greenness": 0},
    )
    assert plan["style"] == "coastal_zen"
    assert plan["basis"] == "palette"


def test_only_three_stock_lanes_no_paid_api():
    cues = search_phrases({"style": "americana"})
    assert cues == [ROLE_QUERIES["woman"], ROLE_QUERIES["skater"],
                    "California desert road sunset"]
    assert len(cues) == 3
    assert "woman portrait" in query_ladder(cues[0])
    assert query_ladder(cues[1])[-1] == "skateboarding"


def test_role_candidates_prioritized_without_new_network_calls():
    base = Video("a", "pexels", vertical=True, query="ocean coastline sunrise")
    women = [Video(f"w{i}", "pexels", vertical=True,
                   query=ROLE_QUERIES["woman"]) for i in range(3)]
    skaters = [Video(f"s{i}", "coverr", vertical=False,
                     query=ROLE_QUERIES["skater"]) for i in range(3)]
    order = prioritize_candidates([base, *women, *skaters])
    assert [v.id for v in order[:4]] == ["w0", "w1", "s0", "s1"]
    assert is_role_candidate(order[0])
    assert not is_role_candidate(base)
    assert len(order) == 7


def test_distinct_woman_and_skater_verified_by_image_scores():
    scores = [
        {"woman": (0.34, 0.25), "skater": (0.21, 0.26)},
        {"woman": (0.22, 0.27), "skater": (0.38, 0.24)},
        {"woman": (0.26, 0.25), "skater": (0.23, 0.22)},
    ]
    result = choose_verified_roles(scores)
    assert result["woman"]["index"] == 0
    assert result["skater"]["index"] == 1


def test_same_clip_for_both_roles_is_not_sufficient():
    with pytest.raises(RuntimeError, match="two distinct clips"):
        choose_verified_roles([{"woman": (0.35, 0.25),
                                "skater": (0.32, 0.20)}])


def test_no_model_evidence_cannot_authorize_roles():
    with pytest.raises(RuntimeError, match="woman"):
        choose_verified_roles([{"woman": (0.18, 0.15),
                                "skater": (0.35, 0.18)},
                               {}])


def test_beat_aligned_storyboard_must_include_both_roles():
    durations = [1.2, 1.2, 1.3, 1.2, 1.2, 1.2]
    shots = build_storyboard(durations, [9.0] * 5, seed="test",
                             no_bookend={1, 2}, featured_sources=(1, 2))
    assert shots[1].source_index == 1
    assert shots[2].source_index == 2
    assert shots[0].source_index not in (1, 2)
    assert shots[-1].source_index not in (1, 2)
    assert [round(x.duration, 1) for x in shots] == durations


def test_featured_storyboard_fails_without_two_distinct_shots():
    with pytest.raises(ValueError, match="distinct"):
        build_storyboard([1, 1, 1, 1], [5, 5], featured_sources=(0, 0))
    with pytest.raises(ValueError, match="four"):
        build_storyboard([1, 1, 1], [5, 5], featured_sources=(0, 1))


def test_old_storyboard_has_no_required_roles():
    shots = build_storyboard([1, 2, 1], [8, 8, 8], seed="classic")
    assert len(shots) == 3
