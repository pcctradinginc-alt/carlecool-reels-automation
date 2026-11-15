"""Video montage using FFmpeg; hard cuts placed on estimated 8-beat boundaries."""
from __future__ import annotations

from pathlib import Path
import os
import json
import subprocess

from .analysis import AudioFeatures, beat_cut_lengths


def _run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe_duration(path: Path) -> float:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(p.stdout)["format"]["duration"])


def render_reel(audio: Path, videos: list[Path], features: AudioFeatures, output: Path, length=30) -> dict:
    if not videos:
        raise ValueError("No licensed videos available")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / "parts"
    work.mkdir(exist_ok=True)
    width = int(os.getenv('REEL_WIDTH', '1080'))
    height = int(os.getenv('REEL_HEIGHT', '1920'))
    if (width, height) not in ((1080, 1920), (270, 480)):
        raise ValueError('Only 1080x1920 production or 270x480 offline test rendering permitted')
    intervals = beat_cut_lengths(features.bpm, length)
    files = []
    for index, seconds in enumerate(intervals):
        source = videos[index % len(videos)]
        duration = probe_duration(source)
        if duration < 1:
            raise ValueError(f"Video too short: {source}")
        # Loop short, cleared footage, then normalize dimensions/frame rate/codec.
        part = work / f"clip_{index:03}.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-stream_loop", "-1", "-i", str(source), "-t", f"{seconds:.3f}",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps=30,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-g", "60", "-video_track_timescale", "30000", str(part),
        ])
        files.append(part)
    concat_path = work / "concat.txt"
    # FFmpeg concat demuxer does not parse shell quoting; enforce simple generated filenames.
    concat_path.write_text("".join(f"file '{p.name}'\n" for p in files), encoding="utf-8")
    video_only = work / "joined.mp4"
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
          "-i", str(concat_path), "-c", "copy", str(video_only)])
    # Respect original audio source; original footage audio is fully removed.
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_only),
        "-ss", f"{features.excerpt_start:.3f}", "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-t", str(length),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-af", f"afade=t=in:st=0:d=0.2,afade=t=out:st={length-0.5}:d=0.5",
        "-movflags", "+faststart", "-shortest", str(output),
    ])
    if output.stat().st_size > 950_000_000:
        raise RuntimeError("Output exceeds safe Instagram upload size")
    return {"duration": probe_duration(output), "scenes": len(files), "resolution": f"{width}x{height}"}
