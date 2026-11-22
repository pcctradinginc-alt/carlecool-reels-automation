"""Cover end card, cover-led style packages and signature shots (offline)."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from carlecool import signature, style
from carlecool.cinematic import Shot
from carlecool.creative import apply_commands, default_profile, interpret_revision, validate_profile
from carlecool.video import Video


# ---------- style packages ----------

class _Music:
    def __init__(self, bpm=128.0, mood="nightdrive", beat_energy=(0.7, 0.8, 0.6)):
        self.bpm, self.mood, self.beat_energy = bpm, mood, beat_energy


def test_dark_cover_adds_night_variant_to_the_recognised_world():
    d = style.decide({"lana": (0.31, "an american flag waving in the wind"), "rubin": (0.2, "x")},
                     brightness=0.12)
    assert d["style"] == "lana" and d["variant"] == "night" and "night" in d["basis"]
    assert style.label(d).endswith("Night")


def test_clear_cover_wins_otherwise_the_music_decides():
    rider = "a rider on a horse with an american flag"
    clear = style.decide({"lana": (0.29, rider), "rubin": (0.22, "x")}, 0.5, _Music(bpm=90))
    assert clear["style"] == "lana" and style.motif_queries(clear)[0] == "horse riding"
    planet = style.decide({"lana": (0.2, "a"), "rubin": (0.3, "a planet floating in outer space")}, 0.5)
    assert planet["style"] == "rubin" and "planet" in style.motif_queries(planet)
    unclear = {"lana": (0.241, "a"), "rubin": (0.238, "b")}
    assert style.decide(unclear, 0.5, _Music(bpm=96))["style"] == "rubin"       # slow → Rubin
    assert style.decide(unclear, 0.5, _Music(bpm=152))["style"] == "lana"       # flowing → Lana
    assert style.decide(unclear, 0.5, _Music(bpm=130, beat_energy=(0.2, 0.3, 0.4)))["style"] == "rubin"
    assert style.decide({}, None, _Music(mood="calm"))["style"] == "rubin"
    assert style.decide({}, None, None)["style"] == "lana"  # always one of the two worlds


def test_style_only_nudges_v4():
    weights = {"nature": 28, "studio": 22, "americana": 20, "skate": 18, "y2k": 7, "night": 5}
    lana = style.blended_weights(weights, "lana")
    assert lana["americana"] == 35 and lana["skate"] > 0  # 50/50, never replaced
    assert style.blended_weights(weights, "lana", "night")["night"] > lana["night"]
    assert style.blended_weights(weights, None) == weights
    assert style.pace_for("medium", "rubin") == "slow"
    assert style.pace_for("fast", "rubin") == "fast"  # owner choice kept
    assert style.pace_for("medium", "lana") == "medium"
    assert style.grade_filters(None) == [] and style.grade_filters("lana", "night") != style.grade_filters("lana")
    assert style.look("lana")["dissolve"] > 0 and style.look("rubin")["dissolve"] == 0
    assert style.look(None) is None


def test_manual_override_and_off(monkeypatch):
    assert style.analyze(None, override="rubin")["style"] == "rubin"
    forced = style.analyze(None, override="night", features=_Music(bpm=90))
    assert forced["style"] == "rubin" and forced["variant"] == "night"
    monkeypatch.setenv("CARLECOOL_STYLE", "off")
    assert style.analyze(Path("x.jpg"))["style"] is None


def test_revise_style_command_is_whitelisted():
    assert interpret_revision("/revise stil night") == ["style_night"]
    assert interpret_revision("/revise style_lana") == ["style_lana"]
    profile = apply_commands(default_profile(), ["style_rubin"])
    assert profile["style"] == "rubin"
    with pytest.raises(ValueError):
        validate_profile(dict(default_profile(), style="disco"))
    assert interpret_revision("/revise rick rubin") == ["more_rick_rubin"]  # old meaning kept


# ---------- signature shots ----------

def test_slot_search_skips_recent_and_premium_and_stops_early(monkeypatch):
    hits = [{"id": "used", "urls": {"mp4": "https://storage.coverr.co/u.mp4"}},
            {"id": "prem", "is_premium": True, "urls": {"mp4": "https://storage.coverr.co/p.mp4"}},
            *[{"id": f"n{i}", "urls": {"mp4": f"https://storage.coverr.co/{i}.mp4"}, "tags": ["skateboard"]}
              for i in range(5)]]
    calls = []
    monkeypatch.setattr(signature, "_coverr_request", lambda s, k, q, n: calls.append(q) or hits)
    found = signature.search_slot("k", ("skateboard feet", "skatepark"), exclude={"used"}, role="skater")
    assert [v.id for v in found] == ["n0", "n1", "n2", "n3", "n4"]
    assert calls == ["skateboard feet"]  # enough after the first query


def test_rotation_varies_by_run():
    q = ("a", "b", "c")
    starts = {signature._rotate(q, f"run{i}|skater")[0] for i in range(20)}
    assert starts == {"a", "b", "c"}


def test_signature_shots_are_interior_and_bookends_untouched():
    shots = [Shot(i % 3, 0.0, 1.0) for i in range(9)]
    placed = signature.place_signature_shots(shots, [10.0, 10.0, 10.0, 8.0, 6.0],
                                             {"skater": 3, "woman": 4})
    assert placed[0] == shots[0] and placed[-1] == shots[-1]
    idx = {s.source_index: i for i, s in enumerate(placed)}
    assert 0 < idx[3] < idx[4] < 8
    assert placed[idx[3]].source_offset == pytest.approx(3.5)  # middle of the clip


def test_face_check_finds_no_face_in_test_pattern(tmp_path):
    import subprocess
    clip = tmp_path / "t.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=10:d=3",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    assert signature.largest_face_ratio(clip) == 0.0


# ---------- end card + platform cover frame ----------

def test_cover_card_contains_artwork_and_scrim(tmp_path):
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    from carlecool.titlecard import make_cover_card
    cover = tmp_path / "c.png"
    Image.new("RGB", (300, 300), (230, 120, 40)).save(cover)
    card = make_cover_card(cover, "carl e cool", "mikosh", 270, 480, tmp_path / "card.png")
    with Image.open(card) as img:
        assert img.getpixel((135, 192))[:3] == (230, 120, 40)  # artwork centre
        assert 80 < img.getpixel((5, 5))[3] < 200  # translucent scrim
    assert make_cover_card(tmp_path / "missing.png", "a", "b", 270, 480, tmp_path / "x.png") is None


def test_cover_frame_reaches_instagram_and_tiktok():
    from carlecool.zernio import Zernio
    session = MagicMock()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"post": {"_id": "p"}}
    session.post.return_value = resp
    Zernio("zrk_test_long_secret", session=session).publish(
        media_url="https://media.zernio.com/temp/x.mp4", caption="c", target="both",
        instagram_id="ig", tiktok_id="tt", ai_generated=False, sha256="a" * 64,
        issue_number=3, cover_frame_ms=11750)
    body = session.post.call_args.kwargs["json"]
    ig = next(p for p in body["platforms"] if p["platform"] == "instagram")
    assert ig["platformSpecificData"]["thumbOffset"] == 11750
    assert body["tiktokSettings"]["video_cover_timestamp_ms"] == 11750
    from carlecool.approve import _cover_frame
    assert _cover_frame({"cover_frame_ms": 11750}) == 11750
    assert _cover_frame({"cover_frame_ms": "11750"}) is None and _cover_frame({}) is None


def test_signature_never_dominates_short_edits():
    shots = [Shot(i % 2, 0.0, 1.5) for i in range(7)]  # 5 interior shots → at most 3 signature
    placed = signature.place_signature_shots(shots, [10.0, 10.0, 8.0, 8.0, 8.0, 8.0, 8.0],
                                             {"motif": 2, "skater": 3, "woman": 4, "friends": 5,
                                              "americana": 6})
    used = {s.source_index for s in placed}
    assert {3, 4, 5} <= used and not {2, 6} & used  # skater, friends, woman first
    assert sum(1 for s in placed if s.source_index >= 2) == 3
    assert placed[0].source_index < 2 and placed[-1].source_index < 2  # bookends stay v4


def test_friends_and_americana_queries_follow_world_and_night():
    assert "friends laughing" in signature.queries_for("friends", "lana")
    assert "friends walking" in signature.queries_for("friends", "rubin")
    assert "friends night" in signature.queries_for("friends", "rubin", "night")
    assert signature.queries_for("flag", "rubin")[0] == "american flag"
    assert signature.queries_for("car", "lana")[0] == "porsche"  # classic Porsche first
    assert "motel" in signature.queries_for("americana", "lana")
    assert "neon sign" in signature.queries_for("americana", "lana", "night")


def test_no_motif_when_style_unclear_or_manual():
    unclear = style.decide({"lana": (0.241, "a rider on a horse with an american flag"),
                            "rubin": (0.238, "b")}, 0.5)
    assert unclear["style"] and unclear["prompt"] == "" and style.motif_queries(unclear) == ()
    assert style.motif_queries({"style": "lana", "basis": "manual", "prompt": ""}) == ()


def test_low_resolution_landscape_is_framed_not_cropped(tmp_path, monkeypatch):
    import subprocess
    from carlecool.analysis import AudioFeatures
    from carlecool.render import render_reel
    monkeypatch.setenv("REEL_WIDTH", "270")
    monkeypatch.setenv("REEL_HEIGHT", "480")
    old = tmp_path / "old.mp4"
    hd = tmp_path / "hd.mp4"
    audio = tmp_path / "a.mp3"
    run = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
    run("-f", "lavfi", "-i", "testsrc2=s=160x120:r=24:d=4", "-pix_fmt", "yuv420p", str(old))
    run("-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=4", "-pix_fmt", "yuv420p", str(hd))
    run("-f", "lavfi", "-i", "sine=f=220:d=6", str(audio))
    features = AudioFeatures(120.0, 0.5, 0.0, "calm", 6.0)
    d = render_reel(audio, [hd, old], features, tmp_path / "out/r.mp4", 4.0, fit_email=False)
    assert d["framed_shots"] >= 1 and d["smart_cropped_shots"] >= 1


def test_cover_is_fetched_in_the_largest_soundcloud_size(tmp_path):
    from carlecool.cover_visual import artwork_variants, fetch_cover
    url = "https://i1.sndcdn.com/artworks-abc-XyZ-large.jpg"
    assert artwork_variants(url)[:3] == [
        "https://i1.sndcdn.com/artworks-abc-XyZ-t3000x3000.jpg",
        "https://i1.sndcdn.com/artworks-abc-XyZ-original.jpg",
        "https://i1.sndcdn.com/artworks-abc-XyZ-t500x500.jpg"]
    tried = []

    class Resp:
        def __init__(self, ok):
            self.status_code = 200 if ok else 404
            self.headers = {}
        def iter_content(self, n):
            yield b"x" * 4096
        def close(self):
            pass

    class Session:
        def get(self, u, **kw):
            tried.append(u)
            return Resp("t500x500" in u)  # pretend 3000 and original are missing

    assert fetch_cover(url, tmp_path / "c.jpg", session=Session())
    assert [u.rsplit("-", 1)[1] for u in tried] == ["t3000x3000.jpg", "original.jpg", "t500x500.jpg"]


def test_look_plan_follows_the_music():
    from carlecool import look
    from carlecool.analysis import AudioFeatures
    beats = tuple(i * 0.5 for i in range(24))
    energy = tuple(0.2 if t < 4 else 0.95 for t in beats)  # quiet verse, loud hook at 4 s
    f = AudioFeatures(120.0, 1.0, 0.0, "cinematic", 12.0, beats=beats, beat_energy=energy, hook_at=4.0)
    starts, durs = [0.0, 2.0, 4.0, 6.0, 8.0], [2.0] * 5
    lana = look.plan_look(dict(style.look("lana"), bw_shots=0, bw_share=0), f, starts, durs)  # B/W tested separately
    assert lana[1]["dissolve_in"] > 0            # quiet passage: soft dissolve
    assert lana[2]["dissolve_in"] == 0           # the hook stays a hard cut on the beat
    assert lana[1]["slowmo"] > 1 and lana[3]["slowmo"] == 1
    assert lana[0]["slowmo"] == 1 and lana[4]["slowmo"] == 1  # loop seam stays real-time
    assert lana[1]["leak"] and not lana[0]["leak"]
    rubin = look.plan_look(style.look("rubin"), f, starts, durs, seed="x")
    assert all(p["dissolve_in"] == 0 for p in rubin)
    assert rubin[3]["punch_in"] and not rubin[1]["punch_in"] and not rubin[4]["punch_in"]  # loudest interior shot
    assert any(p["brightness"] for p in rubin) and all(abs(p["brightness"]) <= 0.02 for p in rubin)
    assert rubin[0]["brightness"] == 0 and rubin[4]["brightness"] == 0
    assert look.slowmo_factor(1.25, 30.0, 24) == 1.25 and look.slowmo_factor(1.25, 25.0, 24) == 1.0
    graph, out = look.join_graph([2.0, 2.0, 2.0], [0.0, 0.5, 0.0])
    assert "xfade=transition=fade:duration=0.500:offset=2.000" in graph and "concat=n=2" in graph


def test_lana_look_renders_with_dissolves_slowmo_and_leaks(tmp_path, monkeypatch):
    import subprocess
    from carlecool.analysis import AudioFeatures
    from carlecool.render import probe_duration, render_reel
    monkeypatch.setenv("REEL_WIDTH", "270")
    monkeypatch.setenv("REEL_HEIGHT", "480")
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    audio = tmp_path / "a.mp3"
    run = lambda *x: subprocess.run(["ffmpeg", "-v", "error", "-y", *x], check=True)
    run("-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=14", "-pix_fmt", "yuv420p", str(a))
    run("-f", "lavfi", "-i", "testsrc=s=360x640:r=30:d=14", "-pix_fmt", "yuv420p", str(b))
    run("-f", "lavfi", "-i", "sine=f=220:d=14", str(audio))
    beats = tuple(i * 0.5 for i in range(22))
    f = AudioFeatures(120.0, 1.0, 0.0, "cinematic", 12.0, beats=beats, downbeats=beats[::4],
                      beat_energy=tuple(0.9 if t < 3 else 0.3 for t in beats), hook_at=0.0)  # hard cuts, then dissolves
    d = render_reel(audio, [a, b], f, tmp_path / "out/r.mp4", 10.0, fit_email=False,
                    look=style.look("lana"), style_grade=style.grade_filters("lana"))
    assert d["dissolves"] >= 1 and d["slowmo_shots"] >= 1 and d["light_leaks"] >= 1
    assert abs(probe_duration(tmp_path / "out/r.mp4") - 10.0) < 0.05  # length unchanged
    assert d["loop_sealed"] and d["cover_frame_ms"] == 0


def test_loop_seam_is_frame_exact_and_continuous():
    from carlecool import look
    shots = [Shot(0, 0.0, 1.21), Shot(1, 0.0, 1.62), Shot(2, 0.0, 2.04), Shot(1, 2.0, 1.71)]
    exact = look.frame_exact(shots, total_frames=158, fps=24)
    assert sum(round(s.duration * 24) for s in exact) == 158
    assert all(abs(s.duration * 24 - round(s.duration * 24)) < 1e-9 for s in exact)
    sealed, ok = look.seal_loop(exact, [8.0, 8.0, 8.0])
    assert ok and sealed[-1].source_index == sealed[0].source_index == 0
    # the closing shot ends exactly where the opening shot begins
    assert abs(sealed[-1].source_offset + sealed[-1].duration - sealed[0].source_offset) < 1e-3
    short, ok = look.seal_loop(exact, [2.0, 8.0, 8.0])
    assert not ok and short == exact


def test_style_search_words_always_include_a_car_and_the_flag():
    for decision in ({"style": "lana"}, {"style": "rubin"}, {"style": "lana", "variant": "night"}):
        for key in ("a", "b", "c", "d"):
            words = style.search_queries(decision, run_key=key)
            assert len(words) == 5 and "american flag" in words
            assert any(w in ("porsche", "land rover", "classic car") for w in words)
            assert all(len(w.split()) <= 2 for w in words)  # Coverr matches every word
    ladders = style.search_ladders(["porsche", "motel"])
    assert ladders["porsche"][0] == "classic car" and "road" not in ladders["motel"]
    assert style.search_queries({"style": None}) == []


def test_more_signature_room_but_bookends_stay():
    shots = [Shot(i % 2, 0.0, 1.6) for i in range(17)]
    slots = {"skater": 2, "friends": 3, "flag": 4, "woman": 5, "car": 6, "americana": 7, "friends2": 8}
    placed = signature.place_signature_shots(shots, [10.0] * 9, slots)
    used = {s.source_index for s in placed}
    assert set(slots.values()) <= used  # 7 signature shots fit into 17
    assert placed[0].source_index < 2 and placed[-1].source_index < 2


def test_cars_alternate_porsche_and_land_rover():
    firsts = {signature.car_order(signature.queries_for("car", "lana"), str(k))[0] for k in range(12)}
    assert firsts == {"porsche", "land rover"}
    assert style.search_ladders(["land rover"])["land rover"][0] == "defender"
