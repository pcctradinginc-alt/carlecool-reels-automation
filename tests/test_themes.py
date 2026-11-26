"""One theme per Reel (owner, 26 Nov — Reel #54 mixed six worlds)."""
from carlecool import hooktext, signature, stylegate, themes
from carlecool.video import Video


def test_theme_words_are_searchable_and_in_style():
    for key, group in themes.THEMES.items():
        assert 3 <= len(group) <= 5
        for name, info in group.items():
            assert len(info["words"]) >= 8 and info["lines"] and info["label"]
            for w in info["words"]:
                assert len(w.split()) <= 2, w
                assert stylegate.blocked_words(Video("x", "coverr", title=w)) is None, (name, w)
            for role in info["roles"]:
                assert role in signature.DEFAULT_PRIORITY, role


def test_one_theme_per_reel_with_car_and_flag():
    w = themes.words("rubin", None, "studio", "run1", 7)
    assert len(w) == 7 and "american flag" in w
    assert w[0] in ("porsche", "land rover", "range rover", "classic car")
    assert all(x in themes.THEMES["rubin"]["studio"]["words"] for x in w[2:])
    assert themes.roles("rubin", None, "studio")[:2] == ("flag", "car")
    assert "skater" not in themes.roles("lana", None, "coast")
    # night uses the night themes whatever the world
    assert themes.get("lana", "night", "drive") is themes.THEMES["night"]["drive"]
    assert themes.archive_films("lana", "night", "drive", 4) == 0
    assert themes.archive_films("lana", None, "family", 4) == 4


def test_themes_rotate_evenly_per_style():
    hist, seen = [], []
    for k in range(4):
        t = themes.choose("lana", None, hist, f"r{k}")
        seen.append(t)
        hist.append({"style": "lana", "theme": t})
    assert sorted(seen) == sorted(themes.THEMES["lana"])
    # other styles' history does not count
    assert themes.choose("rubin", None, [{"style": "lana", "theme": "studio"}] * 3, "x") in themes.THEMES["rubin"]


def test_text_line_comes_from_the_theme():
    import os
    os.environ["CARLECOOL_TEXT_HOOK"] = "always"
    try:
        lines = themes.lines("rubin", None, "coast")
        assert hooktext.choose("rubin", None, "k", lines=lines) in lines
        assert "studio" not in " ".join(lines)  # Reel #54: studio line without studio pictures
    finally:
        os.environ.pop("CARLECOOL_TEXT_HOOK", None)


def test_modern_landmarks_blocked_but_boats_stay():
    assert stylegate.blocked_words(Video("x", "coverr", title="Timelapse Vessel New York City"))
    assert stylegate.blocked_words(Video("x", "coverr", title="The Vessel sky view"))
    assert stylegate.blocked_words(Video("x", "coverr", title="Old sailing vessel at the dock")) is None
