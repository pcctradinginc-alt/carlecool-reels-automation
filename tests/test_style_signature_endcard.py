"""Cover end card, cover-led style packages and signature shots (offline)."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from carlecool import signature, style
from carlecool.cinematic import Shot
from carlecool.creative import apply_commands, default_profile, interpret_revision, validate_profile
from carlecool.video import Video


# ---------- style packages ----------

def test_dark_cover_is_night_regardless_of_motif():
    d = style.decide({"lana": (0.31, "an american flag waving in the wind")}, brightness=0.12)
    assert d["style"] == "night" and "dark cover" in d["basis"]


def test_clear_motif_wins_and_unclear_falls_back_to_v4():
    rider = "a rider on a horse with an american flag"
    clear = style.decide({"lana": (0.29, rider), "rubin": (0.22, "x"), "night": (0.2, "y")}, 0.5)
    assert clear["style"] == "lana" and style.motif_queries(clear)[0] == "horse riding"
    planet = style.decide({"lana": (0.2, "a"), "rubin": (0.3, "a planet floating in outer space"),
                           "night": (0.21, "b")}, 0.5)
    assert planet["style"] == "rubin" and "planet" in style.motif_queries(planet)
    unclear = style.decide({"lana": (0.241, "a"), "rubin": (0.238, "b"), "night": (0.2, "c")}, 0.5)
    assert unclear["style"] is None


def test_style_only_nudges_v4():
    weights = {"nature": 28, "studio": 22, "americana": 20, "skate": 18, "y2k": 7, "night": 5}
    lana = style.blended_weights(weights, "lana")
    assert lana["americana"] == 40 and lana["skate"] > 0  # 50/50, never replaced
    assert style.blended_weights(weights, None) == weights
    assert style.pace_for("medium", "rubin") == "slow"
    assert style.pace_for("fast", "rubin") == "fast"  # owner choice kept
    assert style.pace_for("medium", "lana") == "medium"
    assert style.grade_filters(None) == [] and style.grade_filters("night")


def test_manual_override_and_off(monkeypatch):
    assert style.analyze(None, override="night")["style"] == "night"
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
    shots = [Shot(i % 2, 0.0, 1.5) for i in range(7)]  # calm Rubin edit: 5 interior shots
    placed = signature.place_signature_shots(shots, [10.0, 10.0, 8.0, 8.0, 8.0],
                                             {"motif": 2, "skater": 3, "woman": 4})
    used = {s.source_index for s in placed}
    assert {3, 4} <= used and 2 not in used  # skater + woman kept, motif dropped
    assert sum(1 for s in placed if s.source_index >= 2) == 2
