"""No repeated pictures: within a Reel (storyboard + near-duplicates) and across Reels."""
from collections import Counter
import subprocess

import pytest

from carlecool import dedupe
from carlecool.cinematic import build_storyboard


@pytest.mark.parametrize("shots,clips", [(17, 17), (17, 15), (13, 15), (15, 11)])
def test_no_clip_repeats_while_another_is_unused(shots, clips):
    for seed in range(30):
        board = build_storyboard([1.6] * shots, [8.0] * clips, seed=str(seed))
        uses = Counter(s.source_index for s in board[:-1])  # last shot = loop seam (same clip)
        if len(uses) < clips:
            assert max(uses.values()) == 1
        else:
            assert max(uses.values()) <= -(-(shots - 1) // clips)
        assert all(a.source_index != b.source_index for a, b in zip(board, board[1:]))


def _clip(path, src):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", src, "-t", "3",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_same_picture_with_a_different_id_is_detected(tmp_path):
    a = _clip(tmp_path / "a.mp4", "testsrc2=s=320x568:r=24")
    regraded = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(a), "-vf", "eq=saturation=0.6:brightness=0.03",
                    str(regraded)], check=True)
    other = _clip(tmp_path / "c.mp4", "mandelbrot=s=320x568:r=24")
    lib = dedupe.Library()
    lib.clip = None  # hash path only (no model in unit tests)
    twin, sig = lib.duplicate_of(a)
    assert twin is None
    lib.add("A", sig)
    assert lib.duplicate_of(regraded)[0] == "A"
    assert lib.duplicate_of(other)[0] is None


def test_unreadable_clip_is_never_called_a_duplicate(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"not a video")
    assert dedupe.signature(bad) is None
    assert not dedupe.same_picture(None, dedupe.Signature([0, 0, 0]))



def test_strongest_clip_opens_and_can_close_the_loop():
    from carlecool.look import strongest_opening
    pool = [0, 1, 2, 3]                      # cover-ranking order
    motion = [1.0, 9.0, 8.0, 0.5]
    dims = [(1920, 1080), (3840, 2160), (1280, 720), (1080, 1920)]
    durations = [12.0, 15.0, 9.0, 20.0]
    assert strongest_opening(pool, motion, dims, durations) == 1   # lively + sharp
    durations[1] = 3.0                                              # too short to seal the loop
    assert strongest_opening(pool, motion, dims, durations) == 0   # best cover match, still lively
    assert strongest_opening([], motion, dims, durations) is None


def test_at_most_two_clips_per_motif_and_opening_must_fit_the_style():
    from carlecool.main import MAX_PER_MOTIF, motif_of
    from carlecool.video import Video
    from carlecool.look import strongest_opening
    assert MAX_PER_MOTIF == 2
    assert motif_of(Video("a", "coverr", query="Sailboat ")) == "sailboat"
    assert motif_of(Video("b", "owned", query="x")) == ""
    # Reel #46: a lively, sharp speedboat (index 0) with the worst style fit must not open
    pool, motion = [0, 1, 2, 3, 4, 5], [0.9, 0.3, 0.3, 0.2, 0.2, 0.1]
    dims, durations = [(1080, 1920)] * 6, [10.0] * 6
    fit = {0: -0.05, 1: 0.30, 2: 0.25, 3: 0.10, 4: 0.05, 5: 0.0}
    assert strongest_opening(pool, motion, dims, durations, style_fit=fit) in (1, 2)
