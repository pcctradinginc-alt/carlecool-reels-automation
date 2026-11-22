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
