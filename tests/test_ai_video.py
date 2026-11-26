"""No-network tests for free LTX ZeroGPU experimental adapter."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from carlecool import ai_video


class FakeClient:
    def __init__(self, video):
        self.video = video
        self.calls = []
    def view_api(self, **kwargs):
        return {"named_endpoints": {"/generate_video": {"parameters": []}}}
    def submit(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        class Future:
            def result(inner, timeout):
                assert timeout <= 240
                return ({"video": str(self.video)}, 42)
        return Future()


def test_official_free_space_prompt_is_original_and_bounded():
    s = ai_video.storyboard_prompt("california coastal highway sunset")
    assert "coastal highway" in s
    assert "no celebrity faces" in s
    assert len(s) <= 800
    with pytest.raises(ValueError):
        ai_video.storyboard_prompt("")


def test_probe_sees_public_generation_endpoint():
    assert ai_video.probe(client=FakeClient(None))


def test_ai_video_invoked_exactly_once_without_uploading_music(tmp_path, monkeypatch):
    src = tmp_path / "from_hf.mp4"
    src.write_bytes(b"x" * 4096)
    out = tmp_path / "clip.mp4"
    client = FakeClient(src)
    monkeypatch.setattr(ai_video, "_valid_video", lambda path: True)
    assert ai_video.generate_one("sunset", out, client=client) == out
    assert out.read_bytes() == src.read_bytes()
    assert len(client.calls) == 1
    args, kwargs = client.calls[0]
    assert args[0] is None  # no uploaded music or private image
    assert args[2:] == (2.0, False, args[4], False, 768, 512)
    assert kwargs == {"api_name": "/generate_video"}


def test_invalid_gradio_file_rejected_without_network():
    with pytest.raises(ai_video.AIUnavailable):
        ai_video._result_path(({"video": "https://somewhere.invalid/movie.mp4"}, 5))


def test_ai_unavailable_fails_cleanly_without_leaving_partial_media(tmp_path):
    class FailingClient(FakeClient):
        def submit(self, *args, **kwargs):
            raise RuntimeError("Remote signed secrets must not be printed!")
    dest = tmp_path / "partial.mp4"
    with pytest.raises(ai_video.AIUnavailable, match="RuntimeError"):
        ai_video.generate_one("sunset", dest, client=FailingClient(None))
    assert not dest.exists()


def test_daily_pipeline_ai_is_strictly_opt_in():
    from carlecool.creative import load_profile, default_profile, apply_commands
    content = Path(".github/workflows/daily-reel.yml").read_text()
    assert type(load_profile()["ai_video"]) is bool
    assert default_profile()["ai_video"] is False
    assert "CARLECOOL_AI_VIDEO: 'one'" in content
    assert apply_commands(load_profile(), ["ai_video"])["ai_video"] is True
    assert apply_commands(apply_commands(load_profile(), ["ai_video"]),
                          ["coverr_only"])["ai_video"] is False
    assert "upload-artifact" not in Path(
        ".github/workflows/free-ai-video-smoke.yml").read_text()


def test_decode_without_ffprobe(tmp_path, monkeypatch):
    import imageio_ffmpeg
    import subprocess
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    clip = tmp_path / "real.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=128x192:rate=24", "-t", "2",
                    "-c:v", "libx264", str(clip)], check=True)
    monkeypatch.setattr(ai_video.shutil, "which", lambda name: None)
    assert ai_video._valid_video(clip)
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"x" * 4096)
    assert not ai_video._valid_video(broken)


def test_result_filedata_shape(tmp_path):
    clip = tmp_path / "video.mp4"
    clip.write_bytes(b"x" * 4096)
    assert ai_video._result_path(({"path": str(clip)}, 42)) == clip


def test_failure_stage_is_reported_without_remote_details(tmp_path, monkeypatch):
    clip = tmp_path / "video.mp4"
    clip.write_bytes(b"x" * 4096)
    def fail(path):
        raise FileNotFoundError("private path")
    monkeypatch.setattr(ai_video, "_valid_video", fail)
    with pytest.raises(ai_video.AIUnavailable, match="local_decode / FileNotFoundError") as error:
        ai_video.generate_one("sunset", tmp_path / "out.mp4", client=FakeClient(clip))
    assert "private path" not in str(error.value)
