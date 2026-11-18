"""Expose imageio-ffmpeg's bundled encoder in GitHub Actions without apt downloads."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

import imageio_ffmpeg


def main() -> None:
    source = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    if not source.is_file():
        raise RuntimeError(f"Bundled FFmpeg missing: {source}")
    target_dir = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "carlecool-ffmpeg"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "ffmpeg"
    if target.is_symlink() or target.exists():
        target.unlink()
    target.symlink_to(source)
    version = subprocess.run([str(target), "-version"], text=True, capture_output=True, check=True)
    encoders = subprocess.run([str(target), "-hide_banner", "-encoders"], text=True, capture_output=True, check=True)
    if "libx264" not in encoders.stdout or "aac" not in encoders.stdout:
        raise RuntimeError("Bundled FFmpeg lacks required libx264 or AAC encoder")
    print("FFmpeg available:", version.stdout.splitlines()[0])
    print("Required codecs available: libx264, aac")
    github_path = os.environ.get("GITHUB_PATH")
    if github_path:
        with open(github_path, "a", encoding="utf-8") as stream:
            stream.write(str(target_dir) + "\n")
    else:
        print("Add to PATH:", target_dir)


if __name__ == "__main__":
    main()
