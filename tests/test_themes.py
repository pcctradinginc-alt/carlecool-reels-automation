"""One theme per Reel (owner, 26 Nov — Reel #54 mixed six worlds)."""
from carlecool import hooktext, signature, stylegate, themes
from carlecool.video import Video


def test_theme_words_are_searchable_and_in_style():
    for key, group in themes.THEMES.items():
        assert 3 <= len(group) <= 6
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
    assert "skater" not in themes.roles("lana", None, "dynasty")
    # night uses the night themes whatever the world
    assert themes.get("lana", "night", "drive") is themes.THEMES["night"]["drive"]
    assert themes.archive_films("lana", "night", "drive", 4) == 0
    assert themes.archive_films("lana", None, "dynasty", 4) == 2


def test_themes_rotate_evenly_per_style():
    hist, seen = [], []
    for k in range(len(themes.THEMES["lana"])):
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


def test_night_rejects_daylight_but_keeps_neon(tmp_path):
    from PIL import Image, ImageDraw
    day = Image.new("RGB", (120, 200), (170, 190, 210))          # bright sky
    day.save(tmp_path / "day.jpg")
    night = Image.new("RGB", (120, 200), (12, 14, 28))           # dark street
    ImageDraw.Draw(night).rectangle([40, 30, 80, 60], fill=(255, 60, 160))  # neon sign
    night.save(tmp_path / "night.jpg")
    assert stylegate.too_bright_for_night(tmp_path / "day.jpg") is not None
    assert stylegate.too_bright_for_night(tmp_path / "night.jpg") is None
    assert stylegate.too_bright_for_night(tmp_path / "missing.jpg") is None


def test_music_first_theme_choice():
    from types import SimpleNamespace
    quiet = SimpleNamespace(bpm=78, timbre_hz=1400, percussive=0.06, dynamics=3.4)
    groove = SimpleNamespace(bpm=128, timbre_hz=2900, percussive=0.5, dynamics=1.8)
    assert themes.music_classes(quiet) == {"tempo": "slow", "sound": "dark", "drive": "sparse", "space": "spacious"}
    # fresh history: the song decides
    assert themes.choose("rubin", None, [], "r", quiet) == "quiet"
    assert themes.choose("lana", None, [], "r", groove) == "street"
    assert themes.choose("lana", "night", [], "r", groove) == "drive"
    # rotation still wins over time: a theme never gets 2 Reels ahead of the least used
    hist = [{"style": "rubin", "theme": "quiet"}] * 2
    assert themes.choose("rubin", None, hist, "r", quiet) != "quiet"
    # missing measurements: no class, pure rotation
    assert themes.music_classes(SimpleNamespace(bpm=0, timbre_hz=0, percussive=0, dynamics=0)) == {}


def test_unified_creative_director_bible_27_nov():
    """Lana: dynasty, royals, 90s minimalism, street skate, analog music; analog gear in every Reel."""
    assert set(themes.THEMES["lana"]) == {"dynasty", "royals", "minimal", "street", "studio", "hamptons"}
    assert set(themes.THEMES["night"]) == {"drive", "projects", "stadium", "gilded", "skate", "studio"}
    assert themes.roles("lana", None, "dynasty")[:3] == ("flag", "car", "gear")
    assert themes.roles("lana", "night", "studio").count("gear") == 1
    from carlecool import style
    assert style.look("lana")["chroma_shift"] and style.look("lana")["dissolve_below"] >= 0.7
    # motif weights: analog music (25) comes up more often than royals (10)
    hist, seen = [], []
    for k in range(40):
        t = themes.choose("lana", None, hist, f"w{k}")
        seen.append(t)
        hist.append({"style": "lana", "theme": t})
    assert seen.count("studio") > seen.count("royals")


def test_owner_night_bible_27_nov(tmp_path, monkeypatch):
    """Night: 993 drive, Brooklyn/Harlem, stadium floodlights, old money at night; step-print renders."""
    import subprocess
    from carlecool import style
    from carlecool.analysis import AudioFeatures
    from carlecool.render import render_reel
    assert {"drive", "projects", "stadium", "gilded"} <= set(themes.THEMES["night"])
    assert any("993" in p for p in stylegate.WANTED["lana"])
    monkeypatch.setenv("REEL_WIDTH", "270")
    monkeypatch.setenv("REEL_HEIGHT", "480")
    clips = []
    for k in range(3):
        c = tmp_path / f"c{k}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=360x640:r=30:d=10",
                        "-pix_fmt", "yuv420p", str(c)], check=True)
        clips.append(c)
    audio = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=12", str(audio)], check=True)
    beats = tuple(i * 0.5 for i in range(22))
    f = AudioFeatures(120.0, 1.0, 0.0, "nightdrive", 10.0, beats=beats, downbeats=beats[::4],
                      beat_energy=tuple(0.5 for _ in beats))
    d = render_reel(audio, clips, f, tmp_path / "out/r.mp4", 9.0, fit_email=False,
                    look=style.look("lana"), ref_world="night")
    assert abs(d["duration"] - 9.0) < 0.1 and d["bw_shots"] in (0, d["scenes"])


def test_reel_73_is_the_lana_reference(monkeypatch):
    """Owner's favourite (27 Nov): Hamptons theme restored exactly, its clips favoured."""
    from carlecool import decisions, performance
    from carlecool.video import Video
    info = themes.THEMES["lana"]["hamptons"]
    assert "lighthouse" in info["words"] and info["weight"] == max(t.get("weight", 1) for t in themes.THEMES["lana"].values())
    assert themes.roles("lana", None, "hamptons") == ("flag", "car", "woman", "friends")  # no forced gear, like #73
    clips, motifs = decisions.scores({"decisions": []})
    assert clips["w7ZdjFecqV"] == decisions.FAVOURITE_WEIGHT and motifs["lighthouse"] == decisions.FAVOURITE_WEIGHT
    assert decisions.adjustment(Video("w7ZdjFecqV", "coverr", query="lighthouse"), clips, motifs) > 0
    monkeypatch.setenv("CARLECOOL_THEME", "hamptons")
    assert themes.choose("lana", None, [], "r") == "hamptons"
    monkeypatch.setenv("CARLECOOL_LENGTH", "short")
    assert performance.choose_length("t", [], 30, "r")["bucket"] == "short"
