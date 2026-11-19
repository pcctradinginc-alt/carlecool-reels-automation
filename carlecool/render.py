"""Video montage using FFmpeg; hard cuts placed on estimated 8-beat boundaries."""
from __future__ import annotations

from pathlib import Path
import os
import json
import subprocess

from .analysis import AudioFeatures
from .cinematic import plan_cuts, build_storyboard
from .music_structure import align_to_structure


def _run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe_duration(path: Path) -> float:
    """Read duration via ffprobe where available, otherwise bundled FFmpeg metadata.

    imageio-ffmpeg bundles FFmpeg but not ffprobe. The Duration field is read from
    FFmpeg's input inspection; no media is transcoded during this check.
    """
    import shutil
    import re

    if shutil.which("ffprobe"):
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(p.stdout)["format"]["duration"])
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path)],
        capture_output=True, text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    if not match:
        raise RuntimeError(f"Cannot determine media duration: {path.name}")
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if duration <= 0:
        raise RuntimeError(f"Invalid media duration: {path.name}")
    return duration


def render_reel(audio: Path, videos: list[Path], features: AudioFeatures, output: Path,
                length=30, *, pace="medium", analog=65) -> dict:
    if not videos:
        raise ValueError("No licensed videos available")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / "parts"
    work.mkdir(exist_ok=True)
    width = int(os.getenv('REEL_WIDTH', '1080'))
    height = int(os.getenv('REEL_HEIGHT', '1920'))
    if (width, height) not in ((1080, 1920), (270, 480)):
        raise ValueError('Only 1080x1920 production or 270x480 offline test rendering permitted')
    if pace not in ("slow", "medium", "fast") or type(analog) is not int or not 0 <= analog <= 100:
        raise ValueError("Invalid creative editing controls")
    # Beat-phase-aware, source-offset-aware montage. No stochastic edits.
    intervals = plan_cuts(float(length), float(features.bpm), pace=pace,
                          beat_phase=getattr(features, "beat_phase", 0.0))
    intervals = align_to_structure(intervals, getattr(features, "structure_events", ()))
    source_durations = [probe_duration(path) for path in videos]
    if any(d < 1.0 for d in source_durations):
        raise ValueError("Video too short")
    storyboard = build_storyboard(intervals, source_durations,
                                 seed=str(features.excerpt_start))
    # Quiet, desaturated analogue texture. No false retro footage claim.
    level = analog / 100.0
    saturation = 1.0 - 0.33 * level
    contrast = 1.0 - 0.09 * level
    grain = int(round(7 * level))
    base = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=30,"
            f"eq=saturation={saturation:.3f}:contrast={contrast:.3f}:gamma=1.015,"
            "format=yuv420p")
    filters = base + (f",noise=alls={grain}:allf=u" if grain else "")
    files = []
    for index, shot in enumerate(storyboard):
        seconds = shot.duration
        source = videos[shot.source_index]
        # Loop short, cleared footage, then normalize dimensions/frame rate/codec.
        part = work / f"clip_{index:03}.mp4"
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-stream_loop", "-1", "-ss", f"{shot.source_offset:.3f}", "-i", str(source), "-t", f"{seconds:.3f}",
            "-vf", filters,
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
    # Public GitHub Actions cannot store originals. Deliver exact original as a
    # Gmail attachment; preserve 1080x1920 but keep MIME/base64 below Gmail limits.
    from .mailstore import MAX_ATTACHMENT_BYTES
    if output.stat().st_size > MAX_ATTACHMENT_BYTES:
        compressed = output.with_name("compressed_original.mp4")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(output),
              "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", "veryfast",
              "-b:v", "2500k", "-maxrate", "2900k", "-bufsize", "5800k", "-pix_fmt", "yuv420p",
              "-c:a", "copy", "-movflags", "+faststart", str(compressed)])
        os.replace(compressed, output)
    if output.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise RuntimeError("Reel exceeds safe Gmail attachment limit after compression")
    return {"duration": probe_duration(output), "scenes": len(files),
            "resolution": f"{width}x{height}", "pace": pace, "analog": analog,
            "edit_plan": [{"source_index": s.source_index,
                           "source_offset": s.source_offset,
                           "duration": s.duration} for s in storyboard]}
