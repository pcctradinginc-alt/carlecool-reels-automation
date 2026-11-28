"""Package D (27 Nov): three storyboards scored before rendering, independent Visual Critic."""
import subprocess

from carlecool import critic
from carlecool.cinematic import Shot


def _dna(size, q, lab=(60, 5, 10)):
    return {"lab": list(lab), "luma": 0.5, "contrast": 0.4, "motion": 3.0, "shot_size": size,
            "ref_score": 0.3, "warmth": lab[2], "quality": q, "embedding": None}


def test_plan_score_prefers_quality_variety_and_no_repeats():
    dna = [_dna("wide", 0.9), _dna("close", 0.8), _dna("medium", 0.85), _dna("wide", 0.3)]
    good = [Shot(0, 0, 2), Shot(1, 0, 2), Shot(2, 0, 2), Shot(0, 2, 2)]
    flat = [Shot(3, 0, 2), Shot(0, 0, 2), Shot(3, 2, 2), Shot(0, 2, 2)]  # weak clip, wide-wide-wide-wide
    a, b = critic.plan_score(good, dna), critic.plan_score(flat, dna)
    assert a["total"] > b["total"] and a["variety"] > b["variety"] and a["opening"] > b["opening"]


def _video(path, src):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_critic_flags_monotony_choppy_cuts_and_repeats(tmp_path):
    flat = _video(tmp_path / "flat.mp4", "color=c=gray:s=108x192:r=24:d=4")
    plan = [{"source_index": 0, "duration": 2.0}, {"source_index": 0, "duration": 0.3},
            {"source_index": 1, "duration": 1.7}]
    v = critic.review(flat, {"edit_plan": plan, "coherence": 0.3, "loop_sealed": True})
    joined = " ".join(v["issues"])
    assert "monotonous" in joined and "choppy" in joined and "twice in a row" in joined and "incoherent" in joined
    assert v["retry"] and v["score"] < 0.5


def test_critic_passes_a_lively_coherent_edit(tmp_path):
    lively = _video(tmp_path / "live.mp4", "testsrc2=s=108x192:r=24:d=4,hue=h=90*t:s=0.5:b=2*sin(t*2)")
    plan = [{"source_index": 0, "duration": 2.0}, {"source_index": 1, "duration": 2.0}]
    v = critic.review(lively, {"edit_plan": plan, "coherence": 0.8, "loop_sealed": True})
    assert v["issues"] == [] and not v["retry"] and v["score"] > 0.9


def test_material_limited_reels_are_not_re_edited(tmp_path):
    lively = _video(tmp_path / "m.mp4", "testsrc2=s=108x192:r=24:d=4,hue=h=90*t:s=0.5:b=2*sin(t*2)")
    plan = [{"source_index": 0, "duration": 2.0}, {"source_index": 1, "duration": 2.0}]
    edit = critic.review(lively, {"edit_plan": plan, "coherence": 0.38, "material_coherence": 0.45,
                                  "loop_sealed": True}, compression=False)
    assert any(i.startswith("incoherent") for i in edit["aesthetic"]) and edit["retry"]
    mat = critic.review(lively, {"edit_plan": plan, "coherence": 0.40, "material_coherence": 0.39,
                                 "loop_sealed": True}, compression=False)
    assert mat["material_limited"] and not mat["retry"]
    assert any(i.startswith("material does not fit") for i in mat["aesthetic"])


def test_pool_coherence_is_the_mean_pairwise_fit():
    from carlecool import coherence
    d = {"lab": [50, 0, 0], "luma": 0.5, "contrast": 0.4, "motion": 3, "shot_size": "medium", "ref_score": 0.3, "warmth": 0}
    assert coherence.pool_coherence([d, dict(d), None]) > 0.6
    assert coherence.pool_coherence([d]) is None
