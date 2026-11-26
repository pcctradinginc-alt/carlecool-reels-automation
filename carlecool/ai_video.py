"""Experimental zero-cost short video generation via official Lightricks ZeroGPU.

Off by default. The only external data is a public-safe art-direction prompt:
NO private music, MP4 previews, usernames, or secrets are sent to Spaces.
This uses a community-shared free quota, not a paid inference endpoint.
"""
from __future__ import annotations

import argparse
from concurrent.futures import TimeoutError as FutureTimeout
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SPACE_ID = "Lightricks/LTX-2-3"
API_NAME = "/generate_video"
MAX_VIDEO_BYTES = 40 * 1024 * 1024


class AIUnavailable(RuntimeError):
    """A non-critical provider limitation; Coverr can safely take over."""


def storyboard_prompt(direction: str) -> str:
    """Keep the request independent of artist identities and copyrighted footage."""
    direction = " ".join(str(direction).split())[:420]
    if not direction or any(c in direction for c in "\x00\r\n"):
        raise ValueError("A scene direction is required")
    return (
        "Two-second original 9:16 cinematic shot for an independent music artist. "
        + direction + ". Beautifully unpolished, emotionally genuine, natural light. "
        "Slow camera move, photorealistic, no commercial posing, no glossy ad look, "
        "no plastic skin, no text, no logos, no subtitles, no celebrity faces or "
        "recreations, no known music-video frames. Vertical portrait format. "
        "Generate video only; final soundtrack will be the artist's own music."
    )[:800]


def _client():
    try:
        from gradio_client import Client
    except ImportError as exc:
        raise AIUnavailable("gradio_client is not installed in this runner") from exc
    # Using a free HF token only uses that account's included ZeroGPU minutes.
    # No automatic buying, paid inference or credit top-ups.
    kwargs = {"verbose": False}
    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        kwargs["token"] = token
    return Client(SPACE_ID, **kwargs)


def probe(client=None) -> bool:
    """Discover public API without spending scarce video-generation quota."""
    client = client or _client()
    # gradio_client 2.x returns None unless return_format="dict" is explicit.
    data = client.view_api(print_info=False, return_format="dict")
    # API names are public. Report only their names (not endpoint descriptions).
    serialized = json.dumps(data, ensure_ascii=True, default=str)
    print("Public Gradio API layout:", str(type(data).__name__))
    print("Generation endpoint advertised:", "generate_video" in serialized)
    print("Fallback predict endpoint advertised:", "/predict" in serialized)
    if "generate_video" not in serialized and "/predict" not in serialized:
        raise AIUnavailable("Lightricks Space generation API is unavailable")
    return True


def _result_path(result) -> Path:
    """Recognize the gr.Video Gradio-client output shape, never a remote URL."""
    video = result[0] if isinstance(result, (tuple, list)) and result else result
    if isinstance(video, dict):
        video = video.get("video", video)
        if isinstance(video, dict):
            video = video.get("path") or video.get("name")
    if not isinstance(video, str) or not video or video.startswith(("http:", "https:")):
        raise AIUnavailable("Gradio did not return a locally downloaded video file")
    path = Path(video)
    if not path.is_file() or path.suffix.lower() not in (".mp4", ".webm", ".mov"):
        raise AIUnavailable("Gradio output was not a valid local video file")
    if not 1024 <= path.stat().st_size <= MAX_VIDEO_BYTES:
        raise AIUnavailable("AI video output violates maximum/minimum file size")
    return path


def _valid_video(path: Path) -> bool:
    """Decode real video frames with the same portable FFmpeg used by production."""
    executable = shutil.which("ffmpeg")
    if not executable:
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            raise AIUnavailable("LOCAL_DECODER_MISSING") from None
    inspection = subprocess.run(
        [executable, "-hide_banner", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-an", "-frames:v", "12", "-f", "null", "-"],
        capture_output=True, timeout=30,
    )
    if inspection.returncode != 0:
        return False
    # A second lightweight check requires a non-empty decoded frame, not just a stream header.
    frame = subprocess.run(
        [executable, "-v", "error", "-i", str(path), "-map", "0:v:0", "-frames:v", "1",
         "-vf", "scale=32:32", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True, timeout=30,
    )
    return frame.returncode == 0 and len(frame.stdout) == 32 * 32 * 3


def generate_one(direction: str, destination: Path, *, client=None,
                 timeout_seconds=190) -> Path:
    """Exactly one 2s generation request, bounded. Do not retry over quota."""
    if not 60 <= timeout_seconds <= 240:
        raise ValueError("Allowed ZeroGPU request timeout is 60..240s")
    prompt = storyboard_prompt(direction)
    seed = int.from_bytes(hashlib.sha256(prompt.encode()).digest()[:4], "big") % (2**31 - 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = "connect"
    try:
        client = client or _client()
        stage = "submit"
        # Lightricks/LTX-2-3 app.py documents:
        # image, prompt, duration, enhance, seed, randomize, height, width.
        job = client.submit(
            None, prompt, 2.0, False, seed, False, 768, 512,
            api_name=API_NAME,
        )
        stage = "remote_result"
        result = job.result(timeout=timeout_seconds)
        stage = "downloaded_file"
        source = _result_path(result)
        stage = "local_decode"
        if not _valid_video(source):
            raise AIUnavailable("Generated file has no decoded video stream")
        stage = "copy"
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        print("AI generation PASS: local video decoded and copied")
        return destination
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        # Never log Gradio exception bodies; they could disclose remote info.
        if isinstance(exc, AIUnavailable):
            raise AIUnavailable(f"{stage}: {exc}") from None
        # Classify upstream failures without leaking remotely supplied
        # exception messages, URLs, signed payloads, or user identifiers.
        detail = str(exc).lower()
        category = (
            "QUOTA" if any(word in detail for word in ("quota", "credits", "rate limit", "429")) else
            "QUEUE_BUSY" if any(word in detail for word in ("queue", "busy", "capacity")) else
            "TIMEOUT" if isinstance(exc, FutureTimeout) or "timeout" in detail else
            "UNAVAILABLE"
        )
        raise AIUnavailable("Free ZeroGPU video generation unavailable: " +
                            category + " / " + stage + " / " + type(exc).__name__) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    if not (args.probe or args.generate):
        raise SystemExit("Only explicit --probe / --generate supported")
    stage = "connect"
    try:
        client = _client()
        print("PASS: Connected to public Lightricks Space client.")
        stage = "schema"
        probe(client)
        print("PASS: Gradio API schema is discoverable.")
        if args.generate:
            stage = "generation"
            with tempfile.TemporaryDirectory(prefix="carlecool-ai-") as temp:
                video = generate_one(
                    "Quiet California coastline, fading afternoon sun, palm silhouettes, "
                    "a lonely winding road and subtle Super 8 warmth",
                    Path(temp) / "experimental_2s.mp4", client=client)
                print("PASS: Actual 2-second ZeroGPU video generated and validated; "
                      "temporary output erased. No GitHub artifact, no email or post.")
    except Exception as exc:
        # AIUnavailable messages are sanitized by this adapter.
        detail = str(exc) if isinstance(exc, AIUnavailable) else type(exc).__name__
        print("UNAVAILABLE: free LTX at " + stage + " / " + detail)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
