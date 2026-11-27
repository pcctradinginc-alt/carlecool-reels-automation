"""Package C (27 Nov): visual coherence — transition scores and a globally optimised order."""
from carlecool import coherence
from carlecool.cinematic import Shot


def _dna(lab, luma, motion, size, ref=0.3):
    return {"lab": lab, "luma": luma, "contrast": 0.4, "motion": motion, "shot_size": size,
            "ref_score": ref, "warmth": lab[2], "embedding": None}


WARM = [_dna([70, 8, 25], 0.6, 2.0, "wide"), _dna([68, 9, 22], 0.58, 3.0, "medium"), _dna([72, 7, 24], 0.62, 2.5, "close")]
COLD = [_dna([25, -2, -18], 0.15, 8.0, "wide"), _dna([22, -3, -20], 0.12, 9.0, "close"), _dna([27, -1, -15], 0.18, 7.0, "medium")]


def test_transition_prefers_continuity_and_varied_shot_sizes():
    near = coherence.transition(WARM[0], WARM[1])
    far = coherence.transition(WARM[0], COLD[0])
    assert near["total"] > far["total"]
    same_size = coherence.transition(WARM[0], dict(WARM[1], shot_size="wide"))
    assert near["composition"] > same_size["composition"]
    assert coherence.transition(None, WARM[0])["total"] == 0.5


def test_sequence_groups_the_look_keeps_locked_shots_and_never_repeats_adjacent():
    dna = WARM + COLD
    # alternating warm / cold as a hash rotation might give it
    shots = [Shot(src, 0.0, 2.0) for src in (0, 3, 1, 4, 2, 5, 0, 3)]
    energies = [0.2, 0.3, 0.3, 0.4, 0.8, 0.9, 0.9, 0.3]
    before = coherence.reel_coherence(shots, dna)
    out, score = coherence.sequence(shots, energies, dna, [8.0] * 6, locked={0, 7})
    assert out[0].source_index == 0 and out[7].source_index == 3
    assert sorted(s.source_index for s in out) == sorted(s.source_index for s in shots)
    assert all(a.source_index != b.source_index for a, b in zip(out, out[1:]))
    assert coherence.reel_coherence(out, dna) > before and score is not None
    # loud passages (4-6) get the moving (cold, high-motion) clips
    assert sum(out[i].source_index >= 3 for i in (4, 5, 6)) >= 2


def test_sequence_without_dna_changes_nothing():
    shots = [Shot(0, 0.0, 2.0), Shot(1, 0.0, 2.0), Shot(2, 0.0, 2.0)]
    assert coherence.sequence(shots, [0.5] * 3, [None, None, None], [8.0] * 3, locked=set()) == (shots, None)
