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
