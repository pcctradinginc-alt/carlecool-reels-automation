"""Strict style gate: conservative approval, no model/palette fallback."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from carlecool import style, visual_gate
from carlecool.visual_gate import Decision, gate_clips, judge_frames


def _scores(positive=0.32, negative=0.17):
    return [positive] + [0.06] * (len(visual_gate.POSITIVE["lana"]) - 1) + [negative] * len(
        visual_gate.HARD_NEGATIVES
    )


def _video(index, *, source="coverr", title="", tags=()):
    return SimpleNamespace(id=f"clip-{index}", source=source, title=title, tags=tags)


def test_strict_mode_defaults_on_and_can_be_explicitly_disabled_for_local_tests(monkeypatch):
    monkeypatch.delenv("CARLECOOL_VISUAL_STRICT", raising=False)
    assert visual_gate.enabled()
    monkeypatch.setenv("CARLECOOL_VISUAL_STRICT", "true")
    assert visual_gate.enabled()
    monkeypatch.setenv("CARLECOOL_VISUAL_STRICT", "off")
    assert not visual_gate.enabled()


def test_each_of_five_frames_must_pass_and_bad_end_frame_is_not_hidden_by_average():
    good = [_scores()] * visual_gate.FRAMES_PER_CLIP
    assert judge_frames(good, positive_count=len(visual_gate.POSITIVE["lana"])).approved
    bad = good[:-1] + [_scores(0.30, 0.38)]
    decision = judge_frames(bad, positive_count=len(visual_gate.POSITIVE["lana"]))
    assert not decision.approved
    assert decision.reason == "negative_match_frame_4"


def test_low_style_score_missing_frame_and_non_finite_values_fail_closed():
    n = len(visual_gate.POSITIVE["lana"])
    assert judge_frames([_scores(0.17, 0.05)], positive_count=n).reason == "off_style_frame_0"
    assert judge_frames([], positive_count=n).reason == "no_decodable_frames"
    assert judge_frames([[0.3] * n], positive_count=n).reason == "invalid_scores_frame_0"
    assert judge_frames([[float("nan")] * (n + 1)], positive_count=n).reason == "invalid_scores_frame_0"


def test_metadata_blacklist_blocks_cartoon_emoji_racing_and_german_traffic():
    for title in (
        "Smiley Emoji Cartoon animation racing cars",
        "German road traffic on a country lane",
        "3D render of a race car",
        "highway traffic with family cars",
    ):
        assert visual_gate._BLOCKED_METADATA.search(title)
    assert not visual_gate._BLOCKED_METADATA.search("California palm trees at dusk")
    assert not visual_gate._BLOCKED_METADATA.search("1960s vintage car parked at desert motel")


def test_gate_checks_every_source_and_remaps_only_approved_indices():
    videos = [
        _video(0), _video(1, source="ai"),
        _video(2, source="archive"), _video(3, source="wikimedia"),
        _video(4, source="owned"),
        _video(5, title="Emoji cartoon racing cars"),
    ]
    paths = [Path(f"dummy_{i}.mp4") for i in range(len(videos))]
    scanned = []

    def scorer(path):
        scanned.append(path)
        return Decision(True, "passed", 0.31, 0.09)

    approved, report = gate_clips(paths, videos, "lana", reel_length=15, scorer=scorer)
    assert approved == [0, 2, 3, 4]
    assert len(scanned) == 4  # no unverified AI and no known-bad metadata is inspected or used
    assert report["world"] == "lana" and report["frames_per_clip"] == 5
    assert {x["reason"] for x in report["rejected"]} == {
        "unverified_ai_source_disabled", "blocked_source_metadata"
    }


def test_gate_will_not_render_when_rejections_leave_too_few_clips():
    videos = [_video(i) for i in range(8)]
    with pytest.raises(RuntimeError, match="minimum 6"):
        gate_clips([Path(f"{i}.mp4") for i in range(8)], videos, "rubin",
                   reel_length=30, scorer=lambda p: Decision(int(p.stem) < 5, "fail"))
    with pytest.raises(RuntimeError, match="requires exactly one"):
        gate_clips([Path("a.mp4")], [_video(0)], "other", reel_length=10,
                   scorer=lambda p: Decision(True, "passed"))


def test_fail_closed_when_model_is_unavailable(monkeypatch):
    def missing_model(world):
        raise RuntimeError("OpenCLIP unavailable")
    monkeypatch.setattr(visual_gate, "_model_scorer", missing_model)
    with pytest.raises(RuntimeError, match="OpenCLIP unavailable"):
        gate_clips([Path("a.mp4")], [_video(0)], "rubin", reel_length=10)


def test_failed_frame_inspection_is_never_treated_as_approval():
    def broken(path):
        if path.stem == "0":
            raise ValueError("undecodable")
        return Decision(True, "passed", 0.3, 0.05)
    videos = [_video(i) for i in range(5)]
    keep, report = gate_clips([Path(f"{i}.mp4") for i in range(5)],
                              videos, "lana", reel_length=10, scorer=broken)
    assert keep == [1, 2, 3, 4]
    assert report["rejected"][0]["reason"] == "inspection_failed_ValueError"


def test_production_workflow_requires_style_gate_and_disables_ai():
    from pathlib import Path
    workflow = Path(".github/workflows/daily-reel.yml").read_text(encoding="utf-8")
    assert "CARLECOOL_VISUAL_STRICT: 'true'" in workflow
    assert "CARLECOOL_AI_VIDEO: 'off'" in workflow
    assert "CARLECOOL_SEMANTIC: 'on'" in workflow


def test_worlds_have_distinct_content_descriptions():
    assert "lana" in visual_gate.POSITIVE and "rubin" in visual_gate.POSITIVE
    assert set(visual_gate.POSITIVE["lana"]).isdisjoint(visual_gate.POSITIVE["rubin"])
    assert len(visual_gate.HARD_NEGATIVES) >= 12
    assert "american flag" not in style.search_queries({"style": "rubin"}, run_key="strict")
