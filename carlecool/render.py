"""Video montage using FFmpeg: beat-driven cuts, cover-matched grade, 24 fps master.

Quality choices (and why):
* 24 fps: filmic motion and no judder from mixed 24/25/30 fps stock being forced to 30.
* Lanczos scaling: sharper 1080×1920 than the default bicubic when upscaling stock.
* Per-clip 3D LUT towards the album cover palette (see grading.py).
* x264 CRF 18 (`-tune grain` when grain is added) so the master survives Instagram's
  own re-encode; 256 kb/s AAC normalised to −14 LUFS / −1 dBTP (Reels loudness).
* Only when no external master storage is configured is the master squeezed under the
  Gmail attachment limit (legacy behaviour, visibly softer).
"""
from __future__ import annotations

from pathlib import Path
import os
import json
import subprocess

from .analysis import AudioFeatures
from .cinematic import FPS, build_storyboard, plan_cuts, plan_cuts_from_beats, snap_to_frames
from .music_structure import align_to_structure


def _run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _ffprobe_json(path: Path, entries: str) -> dict | None:
    import shutil
    if not shutil.which("ffprobe"):
        return None
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entries,
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


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


def probe_dimensions(path: Path) -> tuple[int, int]:
    """(width, height) after rotation metadata, via ffprobe or FFmpeg's stream line."""
    import re
    data = _ffprobe_json(path, "stream=width,height:stream_side_data=rotation:stream_tags=rotate")
    if data is not None:
        stream = (data.get("streams") or [{}])[0]
        w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
        rotation = str((stream.get("tags") or {}).get("rotate", ""))
        for side in stream.get("side_data_list") or []:
            rotation = str(side.get("rotation", rotation))
        if rotation.lstrip("-") in ("90", "270"):
            w, h = h, w
        return w, h
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    match = re.search(r"Video:.*?(?<![0-9a-fA-Fx])(\d{2,5})x(\d{2,5})(?![0-9])", p.stderr)
    if not match:
        raise RuntimeError(f"Cannot determine video size: {path.name}")
    w, h = int(match.group(1)), int(match.group(2))
    if re.search(r"rotate\s*:\s*-?(90|270)", p.stderr) or re.search(r"rotation of -?90", p.stderr):
        w, h = h, w
    return w, h


def is_portrait(path: Path) -> bool:
    w, h = probe_dimensions(path)
    return h > w > 0


def _filter_path(path: Path) -> str:
    """Quote a file path for use inside an FFmpeg filter argument."""
    text = str(path).replace("\\", "/").replace("'", "")
    return "'" + text.replace(":", "\\:") + "'"


LOUDNESS = "I=-14:TP=-1.0:LRA=11"


def loudness_filter(audio: Path, start: float, length: float) -> str:
    """Two-pass EBU R128: measure the excerpt, then apply a linear gain to −14 LUFS.

    Linear mode keeps the track's own dynamics (no pumping); falls back to one-pass.
    """
    import re
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                           "-i", str(audio), "-af", f"loudnorm={LOUDNESS}:print_format=json",
                           "-f", "null", "-"], capture_output=True, text=True)
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr)
    try:
        data = json.loads(match.group(0)) if match else {}
        values = [float(data[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")]
    except (KeyError, ValueError, TypeError):
        return f"loudnorm={LOUDNESS}"
    if not all(map(lambda v: v == v and abs(v) < 1e6, values)):
        return f"loudnorm={LOUDNESS}"
    i, tp, lra, thresh, offset = values
    return (f"loudnorm={LOUDNESS}:measured_I={i}:measured_TP={tp}:measured_LRA={lra}:"
            f"measured_thresh={thresh}:offset={offset}:linear=true")


def plan_intervals(features: AudioFeatures, length: float, pace: str) -> list[float]:
    beats = getattr(features, "beats", ())
    if beats and getattr(features, "beat_energy", ()):
        intervals = plan_cuts_from_beats(length, beats, features.downbeats, features.beat_energy,
                                         pace=pace, hook_at=getattr(features, "hook_at", 0.0))
    else:
        intervals = plan_cuts(float(length), float(features.bpm), pace=pace,
                              beat_phase=getattr(features, "beat_phase", 0.0))
        intervals = align_to_structure(intervals, getattr(features, "structure_events", ()))
    return snap_to_frames(intervals, float(length))


def render_reel(audio: Path, videos: list[Path], features: AudioFeatures, output: Path,
                length: float = 30, *, pace="medium", analog=65, cover: Path | None = None,
                no_bookend: set[int] | frozenset[int] = frozenset(),
                fit_email: bool = True) -> dict:
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
    length = float(length)
    intervals = plan_intervals(features, length, pace)
    source_durations = [probe_duration(path) for path in videos]
    if any(d < 1.0 for d in source_durations):
        raise ValueError("Video too short")
    storyboard = build_storyboard(intervals, source_durations,
                                 seed=str(features.excerpt_start), no_bookend=set(no_bookend))
    from .grading import cover_luts
    luts = cover_luts(cover, videos, work)
    level = analog / 100.0
    saturation = 1.0 - 0.25 * level
    contrast = 1.0 - 0.07 * level
    grain = int(round(6 * level))
    files = []
    for index, shot in enumerate(storyboard):
        source = videos[shot.source_index]
        chain = [f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
                 f"crop={width}:{height}", "setsar=1", f"fps={FPS}"]
        lut = luts[shot.source_index]
        if lut is not None:
            chain.append(f"lut3d=file={_filter_path(lut)}:interp=tetrahedral")
        chain.append(f"eq=saturation={saturation:.3f}:contrast={contrast:.3f}:gamma=1.015")
        if grain:
            chain.append(f"noise=alls={grain}:allf=t")
        chain.append("format=yuv420p")
        part = work / f"clip_{index:03}.mp4"
        # Seek before input; -stream_loop is only a last resort for sources shorter than the shot.
        loop = ["-stream_loop", "-1"] if source_durations[shot.source_index] - shot.source_offset < shot.duration else []
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            *loop, "-ss", f"{shot.source_offset:.3f}", "-i", str(source),
            "-frames:v", str(max(1, round(shot.duration * FPS))),
            "-vf", ",".join(chain),
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-tune", "grain" if grain else "film", "-profile:v", "high",
            "-maxrate", "16M", "-bufsize", "24M",
            "-g", str(FPS * 2), "-r", str(FPS), "-video_track_timescale", str(FPS * 1000), str(part),
        ])
        files.append(part)
    concat_path = work / "concat.txt"
    # FFmpeg concat demuxer does not parse shell quoting; enforce simple generated filenames.
    concat_path.write_text("".join(f"file '{p.name}'\n" for p in files), encoding="utf-8")
    video_only = work / "joined.mp4"
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
          "-i", str(concat_path), "-c", "copy", str(video_only)])
    fade_out = min(0.35, length / 10)
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_only),
        "-ss", f"{features.excerpt_start:.3f}", "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-t", f"{length:.3f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
        "-af", (f"{loudness_filter(audio, features.excerpt_start, length)},afade=t=in:st=0:d=0.05,"
                f"afade=t=out:st={length - fade_out:.3f}:d={fade_out:.3f}"),
        "-movflags", "+faststart", "-shortest", str(output),
    ])
    compressed_for_email = False
    if fit_email:
        # Legacy: no external master storage → the master must fit a Gmail attachment.
        from .mailstore import MAX_ATTACHMENT_BYTES
        if output.stat().st_size > MAX_ATTACHMENT_BYTES:
            seconds = max(1.0, probe_duration(output))
            kbps = int(MAX_ATTACHMENT_BYTES * 8 / seconds / 1000 * 0.9) - 256
            compressed = output.with_name("compressed_original.mp4")
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(output),
                  "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-preset", "slow",
                  "-b:v", f"{max(1500, kbps)}k", "-maxrate", f"{max(1800, int(kbps * 1.15))}k",
                  "-bufsize", f"{max(3600, kbps * 2)}k", "-pix_fmt", "yuv420p",
                  "-c:a", "copy", "-movflags", "+faststart", str(compressed)])
            os.replace(compressed, output)
            compressed_for_email = True
        if output.stat().st_size > MAX_ATTACHMENT_BYTES:
            raise RuntimeError("Reel exceeds safe Gmail attachment limit after compression")
    return {"duration": probe_duration(output), "scenes": len(files),
            "resolution": f"{width}x{height}", "fps": FPS, "pace": pace, "analog": analog,
            "cover_graded": sum(1 for lut in luts if lut is not None),
            "compressed_for_email": compressed_for_email,
            "edit_plan": [{"source_index": s.source_index,
                           "source_offset": s.source_offset,
                           "duration": s.duration} for s in storyboard]}
