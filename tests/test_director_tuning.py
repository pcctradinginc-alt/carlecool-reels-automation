"""Owner feedback 28 Nov (Reel #87): skaters any gender, coherent clips, instruments, font."""
from pathlib import Path

from carlecool import coherence, directors, hooktext, stylegate, themes
from carlecool.video import Video


def test_skaters_may_be_men_everyone_else_women_only():
    v = lambda t: Video("x", "coverr", title=t)
    assert stylegate.blocked_words(v("Man skateboarding at night")) is None
    assert stylegate.blocked_words(v("Guys at the skatepark")) is None
    assert stylegate.blocked_words(v("Man walking at night")) == "man"
    assert stylegate.blocked_words(v("Teenagers skateboarding"))  # minors stay out
    assert themes.roles("lana", "night", "skate")[3] == "skater" or "skater" in themes.roles("lana", "night", "skate")


def test_outlier_clips_are_left_out_but_signature_and_minimum_kept():
    warm = {"lab": [70, 8, 25], "luma": 0.6, "contrast": 0.4, "motion": 2.0, "shot_size": "medium",
            "ref_score": 0.3, "warmth": 25}
    odd = {"lab": [20, -10, -30], "luma": 0.1, "contrast": 0.9, "motion": 12.0, "shot_size": "wide",
           "ref_score": 0.1, "warmth": -30}
    dna = [warm, dict(warm), dict(warm), dict(warm), dict(warm), odd, dict(odd)]
    assert coherence.outliers(dna, protected=set(), keep_min=4) == {5, 6}
    assert coherence.outliers(dna, protected={5}, keep_min=4) == {6}
    assert coherence.outliers(dna, protected=set(), keep_min=6) == {5} or len(coherence.outliers(dna, set(), 6)) <= 1


def test_instrument_queries_and_twin_peaks_font():
    for name in ("lana", "night"):
        q = directors.get(name)["roles"]["gear"]
        assert "synthesizer" in q and "drum machine" in q and "mixing console" in q
    assert "nara-28907" in stylegate.blocked_clips()
    font = hooktext._font(40)
    assert font is not None and Path(font.path).name == "texgyreadventor-regular.otf"
