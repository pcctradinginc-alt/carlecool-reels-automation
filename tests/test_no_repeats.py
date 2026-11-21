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
