"""Phase 3 (27 Nov): cut-frame transitions, slot functions, match cuts on accents."""
from carlecool import coherence
from carlecool.cinematic import Shot


def _dna(lab_in, lab_out, size="medium", motion=3.0):
    return {"lab": [50, 0, 0], "luma": 0.5, "contrast": 0.4, "motion": motion, "shot_size": size,
            "ref_score": 0.3, "warmth": 0.0, "embedding": None,
            "edge_in": {"lab": lab_in, "luma": lab_in[0] / 100}, "edge_out": {"lab": lab_out, "luma": lab_out[0] / 100}}


def test_transition_uses_the_real_cut_frames():
    # same averages, but A ends dark and B starts bright → poor cut; C starts dark → good cut
    a = _dna([60, 0, 0], [20, 0, 0])
    b = _dna([85, 0, 0], [50, 0, 0])
    c = _dna([22, 0, 0], [50, 0, 0])
    assert coherence.transition(a, c)["total"] > coherence.transition(a, b)["total"]


def test_slot_functions_follow_the_music():
    energies = [0.6, 0.5, 0.2, 0.9, 0.3, 0.6, 0.55, 0.5]
    f = coherence.slot_functions(energies, [i * 2.0 for i in range(8)], accents={5})
    assert f[0] == "hook" and f[-1] == "loop" and f[1] == "establishing" and f[-2] == "resolution"
    assert f[3] == "climax" and f[2] == "atmosphere" and f[5] == "accent" and f[4] == "contrast"
    assert set(f) <= set(coherence.FUNCTIONS)


def test_function_fit_and_match_cut_bonus_change_the_order():
    assert coherence.function_fit("establishing", {"shot_size": "wide"}, 0.5) > \
        coherence.function_fit("establishing", {"shot_size": "close"}, 0.5)
    dna = [_dna([50, 0, 0], [50, 0, 0], "wide"), _dna([50, 0, 0], [50, 0, 0], "close"),
           _dna([50, 0, 0], [50, 0, 0], "wide"), _dna([50, 0, 0], [50, 0, 0], "medium")]
    shots = [Shot(0, 0, 2), Shot(1, 0, 2), Shot(2, 0, 2), Shot(3, 0, 2)]
    out, _ = coherence.sequence(shots, [0.5] * 4, dna, [8.0] * 4, locked={0, 3},
                                functions=["hook", "establishing", "accent", "loop"])
    assert dna[out[1].source_index]["shot_size"] == "wide" and dna[out[2].source_index]["shot_size"] == "close"
