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


def test_reel_length_is_about_30_seconds_in_whole_phrases():
    for bpm in (70, 90, 96, 120, 128, 140, 152, 174):
        length, bars = analysis.choose_reel_length(bpm)
        assert 24 - 1e-6 <= length <= 34 + 1e-6
        assert bars % 4 == 0  # whole 4-bar phrases: the end runs straight into the start
        assert bars and math.isclose(length, bars * 240 / bpm, abs_tol=0.01)
    assert analysis.choose_reel_length(120) == (32.0, 16)
    assert analysis.choose_reel_length(96) == (30.0, 12)


pytest.importorskip("librosa")


def test_librosa_features_beats_downbeats_and_early_hook():
    sr = 22050
    features = analysis._librosa_features(_click_track(), sr, 15, "Electronic", None)
    assert features.analyzer == "librosa"
    assert 112 <= features.bpm <= 128
    assert 9 <= features.reel_length <= 19  # target 15 → whole phrases around it
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
def test_bar_based_cuts_land_on_downbeats_and_breathe_in_calm_parts(pace):
    beats, downs, energy = _timeline(seconds=16.0)  # 120 BPM → 2 s bars, peak from 8 s
    cuts = plan_cuts_from_beats(16.0, beats, downs, energy, pace=pace, hook_at=8.0)
    assert math.isclose(sum(cuts), 16.0, abs_tol=1e-3)
    assert min(cuts) >= 0.9  # no flicker
    edges = list(np.cumsum(cuts)[:-1])
    frame = 1 / FPS
    # every cut sits on a bar start ("the one"; half-bar only in fast pace), one frame early
    grid = list(downs) + ([d + 1.0 for d in downs] if pace == "fast" else [])
    assert all(any(abs(e + frame - d) < 1e-3 for d in grid) for e in edges)
    assert any(abs(e + frame - 8.0) < 1e-3 for e in edges)  # picture changes on the hook
    calm = [c for c, start in zip(cuts, [0.0] + edges) if start + c <= 8.0]
    peak = [c for c, start in zip(cuts, [0.0] + edges) if start >= 8.0 - frame]
    # calm parts are never cut faster than energetic ones (shots capped at ~3.3 s)
    assert sum(peak) / len(peak) <= sum(calm) / len(calm) + 0.05
    assert max(cuts) <= 3.4


def test_fast_song_is_not_cut_every_two_beats():
    beat = 60 / 152  # live case "luère froid": 152 BPM, loud excerpt
    beats = tuple(round(i * beat, 4) for i in range(32))
    cuts = plan_cuts_from_beats(12.6, beats, beats[::4], (0.9,) * 32, pace="medium", hook_at=4 * beat)
    assert len(cuts) <= 8 and min(cuts) >= 1.4


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


def test_slow_song_uses_half_bars_not_five_second_shots():
    beat = 60 / 96  # live case "NAD+": 96 BPM → 2.5 s bars
    beats = tuple(round(i * beat, 4) for i in range(16))
    cuts = plan_cuts_from_beats(10.0, beats, beats[::4], (0.9,) * 16, pace="medium", hook_at=4 * beat)
    assert len(cuts) >= 6 and max(cuts) <= 3.3


def test_cuts_snap_to_the_audible_kick():
    beats, downs, energy = _timeline(seconds=16.0)
    kicks = [d + 0.03 for d in downs]  # real hit 30 ms after the tracked grid
    cuts = plan_cuts_from_beats(16.0, beats, downs, energy, pace="medium", hook_at=8.0, kicks=kicks)
    edges = list(np.cumsum(cuts)[:-1])
    assert all(any(abs(e + 1 / FPS - k) < 1e-3 for k in kicks) for e in edges)
    far = [d + 0.1 for d in downs]  # too far away: keep the grid
    cuts = plan_cuts_from_beats(16.0, beats, downs, energy, pace="medium", hook_at=8.0, kicks=far)
    assert all(any(abs(e + 1 / FPS - d) < 1e-3 for d in downs) for e in np.cumsum(cuts)[:-1])


def test_motion_matching_puts_moving_clips_on_loud_passages():
    from carlecool.cinematic import Shot
    from carlecool.look import match_motion
    shots = [Shot(0, 0, 2), Shot(1, 0, 2), Shot(2, 0, 2), Shot(3, 0, 2), Shot(0, 2, 2)]
    energies = [0.5, 0.95, 0.1, 0.9, 0.5]
    motion = [5.0, 1.0, 9.0, 4.0]  # source 2 moves most, source 1 is calm
    out = match_motion(shots, energies, motion, [20.0] * 4, locked={0, 4})
    assert out[0] == shots[0] and out[4] == shots[4]
    assert out[1].source_index == 2 and out[2].source_index == 1 and out[3].source_index == 3
    assert all(a.source_index != b.source_index for a, b in zip(out, out[1:]))
    assert match_motion(shots, energies, [-1.0] * 4, [20.0] * 4, locked={0, 4}) == shots


def test_audio_end_flows_seamlessly_into_the_start(tmp_path):
    import subprocess
    from carlecool.render import loop_audio_graph
    song = tmp_path / "song.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=201.3:d=12:sample_rate=48000",
                    "-ac", "2", str(song)], check=True)
    out = tmp_path / "loop.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=16x16:d=8", "-i", str(song),
                    "-filter_complex", loop_audio_graph(song, 2.0, 8.0), "-map", "[a]", "-t", "8",
                    "-ac", "1", "-ar", "48000", str(out)], check=True)
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "s16le", "-ac", "1", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    assert abs(len(x) / 48000 - 8.0) < 0.03
    rms = lambda a: float(np.sqrt(np.mean(a ** 2)))
    # No fade-out dip at the end: the last 50 ms are as loud as the middle.
    assert rms(x[-2400:]) > 0.8 * rms(x[len(x) // 2:len(x) // 2 + 2400])
    # The end IS the music right before the excerpt start, so the repeat continues it.
    src = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(song), "-f", "s16le", "-ac", "1", "-"],
                                       capture_output=True, check=True).stdout, dtype=np.int16).astype(np.float64)
    before = src[2 * 48000 - 960:2 * 48000]
    corr = float(np.dot(x[-960:], before) / (np.linalg.norm(x[-960:]) * np.linalg.norm(before)))
    assert corr > 0.99
