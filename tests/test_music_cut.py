"""Owner, 28 Nov ("setze alles um"): editing to the sound, colour matching, continuity."""
from carlecool import coherence, look, render
from carlecool.cinematic import Shot, plan_cuts_from_beats


def _song():
    beats = [i * 0.5 for i in range(40)]
    energy = [0.3] * 8 + [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0] + [1.0] * 8 + [0.3] * 8 + [0.6] * 8
    return beats, beats[::4], energy


def test_cut_density_follows_the_song_sections():
    beats, downs, energy = _song()
    plain = plan_cuts_from_beats(20.0, beats, downs, energy)
    shaped = plan_cuts_from_beats(20.0, beats, downs, energy, sections=True)
    assert abs(sum(shaped) - 20.0) < 1e-6 and len(shaped) > len(plain)
    assert min(shaped[2:8]) < min(plain[2:8])      # the build / peak gets shorter shots
    assert shaped[-1] >= 1.9                        # the last unit is held into the loop


def test_motion_peak_is_moved_onto_the_kick():
    import numpy as np
    tl = np.full(60, 1.0)
    tl[30] = 9.0                                    # a landing at 5.0 s in the source
    shots = [Shot(0, 0, 2.0), Shot(1, 0.0, 2.0), Shot(0, 2.0, 2.0)]
    out = look.align_motion(shots, kicks=[3.0], timelines={1: tl}, source_durations=[10, 10], locked={0, 2})
    assert abs(out[1].source_offset - 4.0) < 0.05  # kick 1.0 s into the shot ↔ peak at 5.0 s


def test_shot_match_and_direction_continuity():
    a = {"edge_out": {"lab": [60, 0, 20]}}
    b = {"edge_in": {"lab": [40, 0, 0]}}
    f = render.shot_match([a, b], 0, 1)
    assert f and f[0].startswith("eq=brightness=0.06") and "colorbalance" in f[1]
    assert render.shot_match([a, b], 0, 0) == []
    right = {"lab": [50, 0, 0], "luma": .5, "contrast": .4, "motion": 3, "camera_motion": 2, "camera_direction": 0}
    left = dict(right, camera_direction=180)
    same = dict(right, camera_direction=10)
    assert coherence.transition(right, same)["motion"] > coherence.transition(right, left)["motion"]


def test_thin_material_merges_shots_instead_of_repeating():
    from carlecool.cinematic import merge_to_count
    iv = [0.96, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0, 3.0, 2.0, 2.0, 2.04]
    out = merge_to_count(iv, 8)
    assert len(out) == 8 and abs(sum(out) - sum(iv)) < 1e-6 and out[0] == 0.96
    assert max(out) <= 4.5
    assert merge_to_count([1.0, 4.0, 4.0, 1.0], 2) == [1.0, 4.0, 4.0, 1.0]  # never beyond 4.5 s
