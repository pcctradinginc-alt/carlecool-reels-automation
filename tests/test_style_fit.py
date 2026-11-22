"""Style fit: per-song memory, music character, style/content gate (Reel #35 lessons)."""
from types import SimpleNamespace

from carlecool import songstyle, style, stylegate
from carlecool.look import strongest_opening
from carlecool.video import Video


def test_song_style_is_remembered_and_forgotten(tmp_path):
    path = tmp_path / "song-styles.json"
    assert songstyle.for_track("2429901348", path) is None
    songstyle.remember("2429901348", "rubin", path)
    assert songstyle.for_track("2429901348", path) == "rubin"
    songstyle.remember("2429901348", "auto", path)
    assert songstyle.for_track("2429901348", path) is None
    path.write_text('{"1": "disco", "x": "lana", "2": "lana"}')
    assert songstyle.load(path) == {"2": "lana"}


def test_owner_verdict_for_chronocyte_horizon_is_in_the_repo():
    assert songstyle.for_track("2429901348") == "rubin"


def _music(**kw):
    base = dict(bpm=123.0, mood="nightdrive", beat_energy=(0.8,) * 8, timbre_hz=2300.0,
                percussive=0.17, dynamics=1.8)
    base.update(kw)
    return SimpleNamespace(**base)


def test_music_character_decides_between_lana_and_rubin():
    # measured values of the owner's tracks
    assert style.music_style(_music(timbre_hz=1496, dynamics=3.0))[0] == "rubin"   # chronocyte horizon
    assert style.music_style(_music(bpm=152, timbre_hz=3492))[0] == "lana"         # luère froid
    assert style.music_style(_music(bpm=129, percussive=0.06, timbre_hz=2835))[0] == "rubin"  # magnetic hush
    assert style.music_style(_music(bpm=143.6, dynamics=11.6, timbre_hz=2648))[0] == "rubin"  # memory fog
    assert style.music_style(_music(bpm=136, timbre_hz=2831))[0] == "lana"         # get there
    # old features without sound character still work (tempo only)
    assert style.music_style(SimpleNamespace(bpm=123.0, mood="x", beat_energy=(0.8,)))[0] == "lana"


def test_word_gate_blocks_cartoons_modern_supercars_and_off_world_places():
    def v(title, tags=()):
        return Video("x", "coverr", title=title, tags=tuple(tags))
    for title in ("Anthropomorphic Fruit Car Chase on Rainy Coastal Road", "Rear view of a Porsche GT3",
                  "Rear view of a Porsche 911 Turbo S", "Street in Mexico City ", "'Hi there' sign",
                  "Volcano and palm trees", "Timelapse journey in Sweden"):
        assert stylegate.blocked_words(v(title)), title
    for title in ("Couple getting out of a Land Rover", "Ripped USA flag", "Bar neon sign",
                  "Group of friends laughing", "Classic Porsche on a country road"):
        assert stylegate.blocked_words(v(title)) is None, title
    assert stylegate.blocked_words(v("City drive", tags=("cartoon",))) == "cartoon"
    assert not stylegate.rejected(None) and stylegate.rejected((-0.02, "a cartoon"))


def test_rank_candidates_drops_blocked_titles_even_without_a_model(tmp_path, monkeypatch):
    from carlecool import curation
    monkeypatch.setattr(curation, "download_thumbnail", lambda *a, **k: None)
    monkeypatch.setenv("CARLECOOL_SEMANTIC", "off")
    good = Video("a", "coverr", title="Friends on a rooftop")
    cartoon = Video("b", "coverr", title="Animated car with a smiley")
    out, _report = curation.rank_candidates([good, cartoon], None, tmp_path, keep=5, world="lana")
    assert [c.id for c in out] == ["a"]


def test_opening_prefers_style_fit_over_pure_motion():
    pool, motion = [0, 1, 2], [9.0, 2.0, 3.0]          # clip 0 = lively but off-style
    dims, durations = [(1920, 1080)] * 3, [12.0] * 3
    fit = {0: -0.01, 1: 0.12, 2: 0.05}
    assert strongest_opening(pool, motion, dims, durations) == 0
    assert strongest_opening(pool, motion, dims, durations, style_fit=fit) == 1


def test_quality_minimum_stops_thin_reels(monkeypatch):
    import pytest
    from carlecool import main, video
    video.COVERR_BLOCK["status"] = None
    main.check_quality([f"c{i}.mp4" for i in range(10)], 13, {})          # 10 ≥ 10 → ok
    with pytest.raises(main.QualityTooLow, match="too few suitable clips"):
        main.check_quality([f"c{i}.mp4" for i in range(7)] + ["c0.mp4"], 13, {"skater": 7})
    video.COVERR_BLOCK["status"] = 403
    with pytest.raises(main.QualityTooLow, match="HTTP 403"):
        main.check_quality(["a.mp4"] * 3, 13, {})
    monkeypatch.setenv("CARLECOOL_MIN_QUALITY", "off")
    main.check_quality(["a.mp4"], 13, {})
    video.COVERR_BLOCK["status"] = None


def test_coverr_block_is_detected_and_stops_further_requests():
    from unittest.mock import MagicMock
    import pytest
    import requests
    from carlecool import video
    video.COVERR_BLOCK["status"] = None
    resp = MagicMock(status_code=403, url="https://api.coverr.co/videos/x/stats/downloads")
    assert video.describe_error(requests.HTTPError(response=resp)) == "HTTPError 403"
    assert video.coverr_blocked() == 403
    session = MagicMock()
    with pytest.raises(RuntimeError, match="blocked earlier"):
        video._coverr_request(session, "k", "motel", 10)
    session.get.assert_not_called()
    video.COVERR_BLOCK["status"] = None
    other = MagicMock(status_code=404, url="https://cdn.example.org/x.mp4")
    assert video.describe_error(requests.HTTPError(response=other)) == "HTTPError 404"
    assert video.coverr_blocked() is None



def test_analog_gear_belongs_to_both_worlds():
    from carlecool import signature
    for world in ("lana", "rubin"):
        qs = signature.queries_for("gear", world)
        assert "turntable" in qs and all(len(q.split()) <= 2 for q in qs)
        assert any("turntable" in w for w in stylegate.WANTED[world])
    assert "gear" in signature.PRIORITY and "gear" in signature.STRICT_ROLES
    assert "turntable" in style.SEARCH_QUERIES["lana"] and "turntable" in style.SEARCH_QUERIES["rubin"]
    v = lambda t: Video("x", "coverr", title=t)
    assert stylegate.blocked_words(v("DJ mixing on a laptop")) == "laptop"
    assert stylegate.blocked_words(v("Kitchen mixer whisking cream"))
    assert stylegate.blocked_words(v("Vinyl record on a turntable")) is None


def test_reel_39_offbrief_clips_are_blocked_and_people_are_not_judged():
    v = lambda t, q="": Video("x", "coverr", title=t, query=q)
    for title in ("Pouring a glass of Coca-Cola", "Video calling near the Christmas tree",
                  "Women with Christmas gift bags", "Construction workers in the city",
                  "Man pours glasses of champagne"):
        assert stylegate.blocked_words(v(title)), title
    # other flags are kept out of the US-flag motif only
    for title in ("Throwing a pride flag", "Running with a pride flag ", "Gay couple wrapped in a pride flag"):
        assert stylegate.flag_mismatch(v(title))
    assert stylegate.flag_mismatch(v("US Flag near the Chrysler Building")) is None
    # couples / friends are never filtered for who they are
    assert stylegate.blocked_words(v("Gay couple representing LGBT community")) is None
    assert stylegate.blocked_words(v("Friends meeting at a cafe")) is None
    assert stylegate.blocked_words(v("Summer holiday road trip")) is None


def test_wikimedia_credit_shows_a_name_not_a_link():
    from carlecool import wikimedia
    assert wikimedia.artist_name("https://www.youtube.com/user/93galas") == "93galas"
    assert wikimedia.artist_name("Jane Doe https://example.org/jane") == "Jane Doe"
    assert wikimedia.credit_line({"license": "CC BY 3.0", "artist": "https://www.youtube.com/user/93galas"}) \
        == "93galas / Wikimedia Commons (CC BY 3.0)"


def test_lana_reference_profile_is_stored_without_images():
    import json
    from pathlib import Path
    doc = json.loads(Path("data/style-refs/lana.json").read_text())
    assert doc["count"] == 54 and len(doc["embedding"]) == 512
    assert doc["palette_target"]["shadow_a"] > 3           # softly rose shadows
    assert not list(Path("data/style-refs").glob("*.jpg")) and not list(Path("data/style-refs").glob("*.png"))
    assert stylegate.load_reference("lana") is not None and stylegate.load_reference("nope") is None
    grade = " ".join(style.grade_filters("lana"))
    assert "vignette" not in grade and "saturation=1.28" in grade


def test_lana_gets_one_black_and_white_moment_on_a_clean_cut():
    from carlecool import look
    from carlecool.analysis import AudioFeatures
    beats = tuple(i * 0.5 for i in range(40))
    f = AudioFeatures(120.0, 1.0, 0.0, "cinematic", 20.0, beats=beats,
                      beat_energy=tuple(0.2 + 0.02 * (i % 9) for i in range(40)), hook_at=8.0)
    starts, durs = [0, 2, 4, 6, 8, 10, 12, 14], [2.0] * 8
    plan = look.plan_look(style.look("lana"), f, starts, durs)
    bw = [i for i, p in enumerate(plan) if p["bw"]]
    assert len(bw) == 2 and 0 not in bw and 7 not in bw   # 20 % of 8 shots → 2
    i = bw[0]
    assert plan[i]["dissolve_in"] == 0 and plan[i + 1]["dissolve_in"] == 0 and not plan[i]["leak"]
    rubin = look.plan_look(style.look("rubin"), f, starts, durs)
    assert sum(p["bw"] for p in rubin) == 2 and all(p.get("bw_contrast", 0) > 1.1 for p in rubin if p["bw"])


def test_rubin_reference_profile_and_look():
    import json
    from pathlib import Path
    doc = json.loads(Path("data/style-refs/rubin.json").read_text())
    assert doc["count"] == 36 and len(doc["embedding"]) == 512
    grade = " ".join(style.grade_filters("rubin"))
    assert "vignette" not in grade and "saturation=0.6" in grade       # muted, deep blacks
    assert style.look("rubin")["bw_share"] == 0.25 and style.look("rubin")["bw_contrast"] > 1.1
    assert "mixing console" in style.SEARCH_QUERIES["rubin"]
    from carlecool import signature
    assert signature.queries_for("gear", "rubin")[0] == "mixing console"


def test_tags_do_not_exclude_harmless_clips_or_people():
    v = lambda t, tags=(): Video("x", "coverr", title=t, tags=tuple(tags))
    assert stylegate.blocked_words(v("Skate park by the beach", ["santa monica", "beach"])) is None
    assert stylegate.blocked_words(v("Hands on a Land Rover steering wheel", ["jungle", "car"])) is None
    assert stylegate.blocked_words(v("Best friends walking to class", ["laptop", "school"])) is None
    assert stylegate.blocked_words(v("Couple kissing during golden hour", ["valentine"])) is None
    assert stylegate.flag_mismatch(v("A gay couple holding hands", ["pride", "lgbt"])) is None
    assert stylegate.flag_mismatch(v("Running with a pride flag")) == "pride flag"
    assert stylegate.blocked_words(v("City drive", ["cartoon"])) == "cartoon"   # synthetic looks still via tags



def test_studio_fashion_portraits_are_blocked():
    v = lambda t: Video("x", "coverr", title=t)
    for title in ("Chic Studio Fashion Portrait with Unique Backdrop", "Model posing in a photoshoot",
                  "Stylish Duo: Fashion Meets Colorful Backdrop"):
        assert stylegate.blocked_words(v(title)), title
    assert stylegate.blocked_words(v("Woman walking on a sunny street")) is None
    assert any("photo studio" in u for u in stylegate.UNWANTED)



def test_cars_follow_the_owners_car_references():
    from carlecool import signature
    assert stylegate.load_reference("car") is not None
    assert style.search_ladders(["range rover"])["range rover"] == ("land rover",)
    assert not any("suv" in n for n in signature.PROMPTS["car"][1])   # modern Range Rover allowed
    assert signature.queries_for("car", "rubin")[:2] == ("land rover", "range rover")



def test_car_profiles_cover_rovers_and_porsche_993():
    refs = stylegate.load_references("car")
    assert len(refs) == 3 and all(len(r) == 512 for r in refs)
    assert stylegate.load_reference("car") is not None and stylegate.load_references("nope") == []
    assert len(stylegate.load_references("lana")) == 1



def test_singer_911_and_owner_people_style():
    from carlecool import signature
    assert "classic porsche" in signature.queries_for("car", "lana")
    assert "woman rain boots" in signature.queries_for("woman", "lana")
    assert "couple walking beach" in signature.queries_for("friends", "lana")
    assert any("wellington" in w for w in stylegate.WANTED["lana"])
    assert any("waxed field jacket" in p for p in signature.PROMPTS["woman"][0])



def test_people_profile_is_style_only_and_stored_without_images():
    import json
    from pathlib import Path
    doc = json.loads(Path("data/style-refs/people.json").read_text())
    assert doc["count"] == 13 and len(doc["embedding"]) == 512 and "RANKING by style only" in doc["note"]
    assert len(stylegate.load_references("people")) == 1
