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


def test_cinematic_search_lanes_are_all_theme_words():
    from carlecool import themes
    w = themes.words("lana", None, "hamptons", "r1", 7, theme_only=True)
    assert len(w) == 7 and "american flag" not in w and all(x in themes.THEMES["lana"]["hamptons"]["words"] for x in w)
    classic = themes.words("lana", None, "hamptons", "r1", 7)
    assert classic[1] == "american flag"


def test_people_shots_are_searched_inside_the_theme():
    from carlecool import signature
    q = signature.queries_for("woman", "lana", None, "studio")
    assert "woman piano" in q and "woman horse" not in q
    assert "woman horse" in signature.queries_for("woman", "lana", None, "royals")
    assert signature.queries_for("car", "lana", None, "studio") == signature.queries_for("car", "lana", None)
