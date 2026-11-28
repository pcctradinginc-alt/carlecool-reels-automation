"""Owner, 28 Nov ("es muss besser werden"): clips must show their motif; music picks the director."""
from carlecool import coherence, stylegate
from carlecool.video import Video


def test_smoking_is_blocked_and_relevance_without_model_is_neutral():
    assert stylegate.blocked_words(Video("x", "coverr", title="Brunette woman smoking outside in the rain"))
    assert stylegate.relevance([None], ["baseball"], None) == [None]
    assert "a basketball court" in stylegate.GENERIC_SCENES and "a river, lake or the sea" in stylegate.GENERIC_SCENES


def test_outlier_selection_is_stricter_now():
    assert coherence.OUTLIER_GAP <= 0.06


def test_basketball_streetball_night_and_tennis_hamptons():
    from carlecool import directors
    night = directors.get("night")["themes"]
    assert {"basketball", "streetball"} <= set(night["stadium"]["words"]) and "streetball" in night["projects"]["words"]
    assert {"tennis", "tennis court"} <= set(directors.get("lana")["themes"]["hamptons"]["words"])
    for w in ("basketball", "streetball", "tennis court"):
        assert stylegate.blocked_words(Video("x", "coverr", title=w)) is None
