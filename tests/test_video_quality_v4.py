"""Offline tests for cover-led curation, beat editing, grading and master storage."""
from email.utils import make_msgid
import hashlib
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from carlecool import analysis, curation, grading, masterstore
from carlecool.cinematic import FPS, build_storyboard, plan_cuts_from_beats, snap_to_frames
from carlecool.video import Video


# ---------- music analysis ----------

def _click_track(bpm=120.0, seconds=40, sr=22050, lift_at=20.0):
    t = np.arange(int(sr * seconds)) / sr
    beat = 60.0 / bpm
    phase = np.mod(t, beat)
    bar_phase = np.mod(t, 4 * beat)
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-30 * phase)
    accent = 1.0 + 1.2 * (bar_phase < beat)  # louder "one"
    hat = 0.15 * np.random.default_rng(1).normal(size=t.size) * np.exp(-60 * np.mod(t + beat / 2, beat))
    gain = np.where(t >= lift_at, 1.0, 0.3)
    return (gain * (0.6 * kick * accent + hat)).astype(np.float32)


def test_reel_length_is_whole_bars_between_8_and_15_seconds():
    for bpm in (70, 90, 120, 128, 140, 174):
        length, bars = analysis.choose_reel_length(bpm)
        assert 8 - 1e-6 <= length <= 15 + 1e-6
        assert bars and math.isclose(length, bars * 240 / bpm, abs_tol=0.01)


pytest.importorskip("librosa")


def test_librosa_features_beats_downbeats_and_early_hook():
    sr = 22050
    features = analysis._librosa_features(_click_track(), sr, 15, "Electronic", None)
    assert features.analyzer == "librosa"
    assert 112 <= features.bpm <= 128
    assert 8 <= features.reel_length <= 15
    assert len(features.beats) == len(features.beat_energy) >= 12
    assert all(b < features.reel_length for b in features.beats)
    # Downbeats every 4 beats, and the energy lift arrives in the first ~3 s.
    gaps = np.diff(features.downbeats)
    assert np.allclose(gaps, 2.0, atol=0.1)
    assert 0.5 <= features.hook_at <= 3.5
    assert math.isclose(features.excerpt_start + features.hook_at, 20.0, abs_tol=0.3)


# ---------- editing ----------

def _timeline(seconds=12.0, bpm=120.0, high_from=6.0):
    beat = 60 / bpm
    beats = tuple(round(i * beat, 3) for i in range(int(seconds / beat)))
    downs = beats[::4]
    energy = tuple(0.9 if b >= high_from else 0.2 for b in beats)
    return beats, downs, energy


@pytest.mark.parametrize("pace", ["slow", "medium", "fast"])
def test_energy_driven_cuts_sum_exactly_and_cut_faster_at_peaks(pace):
    beats, downs, energy = _timeline()
    cuts = plan_cuts_from_beats(12.0, beats, downs, energy, pace=pace, hook_at=6.0)
    assert math.isclose(sum(cuts), 12.0, abs_tol=1e-3)
    assert min(cuts) >= 0.42
    edges = np.cumsum(cuts)[:-1]
    calm = sum(1 for e in edges if e < 6.0)
    peak = sum(1 for e in edges if e >= 6.0)
    assert peak > calm
    assert any(abs(e - 6.0) < 0.01 for e in edges)  # visual change lands on the hook


def test_frame_snapping_is_exact_at_24fps():
    snapped = snap_to_frames([1.01, 2.333, 0.517, 4.0], 7.86)
    assert math.isclose(sum(snapped), round(7.86 * FPS) / FPS, abs_tol=1e-6)
    for d in snapped:
        assert math.isclose(d * FPS, round(d * FPS), abs_tol=1e-3)


def test_ai_clip_never_opens_or_closes_and_long_sources_do_not_loop():
    durations = [1.0] * 12
    shots = build_storyboard(durations, [9.0, 8.0, 7.0, 2.0], seed="x", no_bookend={3})
    assert shots[0].source_index != 3 and shots[-1].source_index != 3
    for shot in shots:
        source = [9.0, 8.0, 7.0, 2.0][shot.source_index]
        assert shot.source_offset + shot.duration <= source + 1e-6
    assert all(shots[i].source_index != shots[i - 1].source_index for i in range(1, len(shots)))


# ---------- colour grading ----------

def test_lut_is_identity_for_matching_stats_and_moves_towards_cover():
    stats = (np.array([50.0, 0.0, 0.0]), np.array([20.0, 10.0, 10.0]))
    identity = grading.transfer_lut(stats, stats, size=5)
    axis = np.linspace(0, 1, 5)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], axis=-1).reshape(-1, 3)
    assert np.allclose(identity, grid, atol=2e-3)
    warm = (np.array([55.0, 12.0, 25.0]), np.array([20.0, 10.0, 10.0]))
    graded = grading.transfer_lut(stats, warm, size=5)
    assert graded[:, 0].mean() > grid[:, 0].mean()  # redder
    assert graded[:, 2].mean() < grid[:, 2].mean()  # less blue


def test_cube_file_format(tmp_path):
    table = grading.transfer_lut((np.zeros(3) + [50, 0, 0], np.ones(3) * 10),
                                 (np.zeros(3) + [50, 0, 0], np.ones(3) * 10), size=3)
    cube = grading.write_cube(table, tmp_path / "x.cube", size=3).read_text().splitlines()
    assert "LUT_3D_SIZE 3" in cube and len([l for l in cube if l[0].isdigit()]) == 27


def test_no_cover_means_no_grading(tmp_path):
    assert grading.cover_luts(None, [tmp_path / "a.mp4"], tmp_path) == [None]


# ---------- cover-led curation ----------

def test_palette_moods():
    warm = curation.lane_scores_from_palette({"brightness": .6, "saturation": .3, "warmth": .25, "greenness": 0})
    dark = curation.lane_scores_from_palette({"brightness": .12, "saturation": .1, "warmth": -.1, "greenness": 0})
    assert max(warm, key=warm.get) == "americana"
    assert max(dark, key=dark.get) == "night"


def test_cover_phrases_come_first_and_lanes_are_not_duplicated():
    choice = {"queries": ["palm trees golden hour", "night drive coastal road"]}
    profile = ["California coastal highway sunset", "vinyl record turntable grooves", "river flowing natural light"]
    merged = curation.merge_queries(choice, profile)
    assert merged[:2] == choice["queries"]
    assert merged[2] == "vinyl record turntable grooves"  # americana already represented


def _video(i, query):
    return Video(f"v{i}", "coverr", url=f"https://storage.coverr.co/{i}.mp4", query=query,
                 thumb_url=f"https://storage.coverr.co/t/{i}.jpg", vertical=True)


def test_rank_before_download_keeps_best_and_every_lane(tmp_path, monkeypatch):
    candidates = [_video(i, "A" if i < 8 else "B") for i in range(12)]
    scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, -1, 0.0]
    monkeypatch.setattr(curation, "download_thumbnail", lambda url, dest, session=None: None)
    monkeypatch.setattr(curation, "score_thumbnails", lambda cover, thumbs, queries: scores)
    owned = Video("own", "owned", path="x.mp4")
    picked, report = curation.rank_candidates(candidates + [owned], None, tmp_path, keep=4)
    ids = [v.id for v in picked]
    assert ids[-1] == "own" and len(ids) == 5
    assert {"v0", "v1", "v8"} <= set(ids)  # best scores plus best clip of lane B
    assert "v10" not in ids  # unscorable thumbnail dropped
    assert len(report) == 4


def test_rank_falls_back_to_discovery_order_when_nothing_scores(tmp_path, monkeypatch):
    candidates = [_video(i, "A") for i in range(10)]
    monkeypatch.setattr(curation, "download_thumbnail", lambda url, dest, session=None: None)
    monkeypatch.setattr(curation, "score_thumbnails", lambda c, t, q: [-1.0] * len(t))
    picked, _ = curation.rank_candidates(candidates, None, tmp_path, keep=3)
    assert [v.id for v in picked] == ["v0", "v1", "v2"]


# ---------- master storage ----------

class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType, Metadata):
        self.objects[(Bucket, Key)] = Body.read()

    def head_object(self, Bucket, Key):
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[(bucket, key)])


def test_master_roundtrip_and_tamper_detection(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTER_S3_BUCKET", "carlecool-private")
    video = tmp_path / "carlecool_1.mp4"
    video.write_bytes(b"MASTER" * 1000)
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    s3 = FakeS3()
    location = masterstore.upload_master(video, run_id=77, sha256=sha, client=s3)
    assert location["key"] == f"carlecool/masters/77/{sha}.mp4"
    restored = masterstore.download_master(location, tmp_path / "out.mp4", expected_sha256=sha, client=s3)
    assert restored.read_bytes() == video.read_bytes()
    s3.objects[("carlecool-private", location["key"])] = b"tampered"
    with pytest.raises(ValueError, match="SHA-256"):
        masterstore.download_master(location, tmp_path / "out2.mp4", expected_sha256=sha, client=s3)
    with pytest.raises(ValueError, match="key"):
        masterstore.download_master(dict(location, key="../x.mp4"), tmp_path / "o.mp4",
                                    expected_sha256=sha, client=s3)
    monkeypatch.setenv("MASTER_S3_BUCKET", "other")
    with pytest.raises(ValueError, match="bucket"):
        masterstore.download_master(location, tmp_path / "o.mp4", expected_sha256=sha, client=s3)


def test_master_mode_emails_preview_and_restores_master(tmp_path, monkeypatch):
    from tests.test_public_gmail import FakeIMAP, FakeSMTP
    from carlecool.mailstore import fetch_reel_from_sent
    from carlecool.review import send_review_email
    monkeypatch.setenv("GMAIL_ADDRESS", "artist@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "app password")
    monkeypatch.setenv("REVIEW_EMAIL", "artist@example.com")
    monkeypatch.setenv("MASTER_S3_BUCKET", "carlecool-private")
    master = tmp_path / "carlecool_5.mp4"
    master.write_bytes(b"FULL QUALITY MASTER" * 2_000_000)  # ~38 MB: too big for Gmail
    sha = hashlib.sha256(master.read_bytes()).hexdigest()
    s3 = FakeS3()
    location = masterstore.upload_master(master, run_id=9, sha256=sha, client=s3)
    metadata = {"sha256": sha, "track_id": "5", "title": "t", "output": "output/carlecool_5.mp4",
                "caption": "c", "master_storage": location}
    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"small preview")
    message_id = make_msgid(domain="carlecool.invalid")
    with patch("carlecool.review.smtplib.SMTP_SSL", FakeSMTP), \
         patch("carlecool.review.make_preview", lambda video, dest: preview):
        assert send_review_email("https://github.com/test/repo/issues/1", metadata, master,
                                 message_id=message_id, run_id=9)
    names = [p.get_filename() for p in FakeSMTP.outgoing.iter_attachments()]
    assert "CarleCool-Preview.mp4" in names and "CarleCool-Original.mp4" not in names
    approval = {"sha256": sha, "track_id": "5", "run_id": 9, "mail_message_id": message_id,
                "master_storage": location}
    with patch("carlecool.masterstore._client", lambda: s3):
        _, restored = fetch_reel_from_sent(approval, tmp_path / "approval",
                                           connection=FakeIMAP(FakeSMTP.outgoing.as_bytes()))
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == sha
