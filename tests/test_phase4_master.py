"""Phase 4 (27 Nov): free full-quality master in the Actions cache, preview fallback."""
import hashlib

import pytest

from carlecool import masterstore


def test_cache_master_roundtrip_and_identity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CARLECOOL_MASTER_STORE", "actions-cache")
    monkeypatch.delenv("MASTER_S3_BUCKET", raising=False)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"master-bytes" * 100)
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    assert masterstore.configured()
    loc = masterstore.upload_master(video, run_id=42, sha256=sha)
    assert loc["provider"] == "actions-cache" and loc["key"] == "carlecool-master-42"
    out = masterstore.download_master(loc, tmp_path / "out.mp4", expected_sha256=sha)
    assert out.read_bytes() == video.read_bytes()
    with pytest.raises(ValueError):
        masterstore.download_master(dict(loc, path="../etc/passwd"), tmp_path / "x.mp4", expected_sha256=sha)
    (tmp_path / loc["path"]).unlink()
    with pytest.raises(FileNotFoundError):  # expired → mailstore falls back to the verified preview
        masterstore.download_master(loc, tmp_path / "y.mp4", expected_sha256=sha)


def test_without_configuration_nothing_changes(monkeypatch):
    monkeypatch.delenv("CARLECOOL_MASTER_STORE", raising=False)
    monkeypatch.delenv("MASTER_S3_BUCKET", raising=False)
    assert not masterstore.configured()


def test_punch_in_folds_into_the_single_zoom_transform():
    from carlecool import reach
    hold = reach.zoom_filters(("hold", 0.0), 2.0, 1080, 1920, base=1.111)
    assert len(hold) == 2 and hold[0].startswith("scale=1200:2134") and hold[1] == "crop=1080:1920"
    assert reach.zoom_filters(("hold", 0.0), 2.0, 1080, 1920) == []
    assert "1.1110+" in reach.zoom_filters(("in", 0.04), 2.0, 1080, 1920, base=1.111)[0]


def test_hook_text_stays_inside_platform_safe_zones(tmp_path):
    from PIL import Image
    from carlecool import hooktext
    path = hooktext.make_png("pov: the last summer at the beach house, nobody is leaving yet " * 3,
                             1080, 1920, tmp_path / "t.png")
    if path is None:
        return  # no font on this machine
    box = Image.open(path).getbbox()
    assert box[1] >= 1920 * hooktext.SAFE_TOP and box[3] <= 1920 * (1 - hooktext.SAFE_BOTTOM) + 8


def test_critic_separates_technical_and_aesthetic(tmp_path):
    import subprocess
    from carlecool import critic
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=108x192:r=24:d=3,hue=s=0.5:h=90*t",
                    "-f", "lavfi", "-i", "sine=f=220:d=3", "-shortest", "-pix_fmt", "yuv420p", str(v)], check=True)
    r = critic.review(v, {"edit_plan": [{"source_index": 0, "duration": 1.5}, {"source_index": 1, "duration": 1.5}],
                          "coherence": 0.8, "loop_sealed": True, "duration": 3.0})
    assert set(r) >= {"technical", "aesthetic", "issues", "measures"}
    assert "platform_ssim" in r["measures"] and "true_peak_dbtp" in r["measures"]
