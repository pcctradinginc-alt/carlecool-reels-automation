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


FRAMED_UPSCALE_LIMIT = 3.0  # crop upscale beyond this → framed presentation
LOOP_BRIDGE_SECONDS = 0.38   # cover card fading out at the start (matches the last frame)
LOOP_CROSSFADE = 0.25        # audio: the end blends into the bar just before the start


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


def loop_audio_graph(audio: Path, start: float, length: float) -> str:
    """Excerpt audio whose end flows straight back into its start (seamless loop).

    The last LOOP_CROSSFADE s are an equal-power crossfade from the music's continuation
    into the audio just BEFORE the excerpt start. When the platform jumps back to 0:00,
    the song therefore continues exactly as it would have — no fade-out dip, no click,
    no gap. Loudness is normalised afterwards (two-pass, −14 LUFS).
    """
    norm = loudness_filter(audio, start, length)
    fade = min(LOOP_CROSSFADE, start, length / 4)
    end = start + length
    if fade < 0.02:  # excerpt starts at 0:00 — nothing before it; just avoid clicks
        return (f"[1:a]atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS,aresample=48000,"
                f"afade=t=in:d=0.005,afade=t=out:st={length - 0.01:.4f}:d=0.01,{norm},"
                f"aresample=48000[a]")
    return (f"[1:a]aresample=48000,asplit=2[s1][s2];"
            f"[s1]atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS,asplit=2[m1][m2];"
            f"[m1]atrim=end={length - fade:.4f}[head];"
            f"[m2]atrim=start={length - fade:.4f},asetpts=PTS-STARTPTS,afade=t=out:d={fade:.4f}:curve=qsin[tail];"
            f"[s2]atrim=start={start - fade:.4f}:end={start:.4f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:d={fade:.4f}:curve=qsin[pre];"
            f"[tail][pre]amix=inputs=2:normalize=0:duration=first[seam];"
            f"[head][seam]concat=n=2:v=0:a=1,{norm},aresample=48000[a]")


def plan_intervals(features: AudioFeatures, length: float, pace: str) -> list[float]:
    beats = getattr(features, "beats", ())
    if beats and getattr(features, "beat_energy", ()):
        intervals = plan_cuts_from_beats(length, beats, features.downbeats, features.beat_energy,
                                         pace=pace, hook_at=getattr(features, "hook_at", 0.0),
                                         kicks=getattr(features, "kicks", ()))
    else:
        intervals = plan_cuts(float(length), float(features.bpm), pace=pace,
                              beat_phase=getattr(features, "beat_phase", 0.0))
        intervals = align_to_structure(intervals, getattr(features, "structure_events", ()))
    return snap_to_frames(intervals, float(length))


def render_reel(audio: Path, videos: list[Path], features: AudioFeatures, output: Path,
                length: float = 30, *, pace="medium", analog=65, cover: Path | None = None,
                no_bookend: set[int] | frozenset[int] = frozenset(),
                fit_email: bool = True, title_card: tuple[str, str] | None = None,
                style_grade: list[str] | None = None,
                signature_slots: dict[str, int] | None = None,
                look: dict | None = None) -> dict:
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
    # Signature clips (cover motif, skater, woman) are accents: excluded from the normal
    # rotation and placed exactly once in an interior shot.
    reserved = set((signature_slots or {}).values())
    base = [i for i in range(len(videos)) if i not in reserved] or list(range(len(videos)))
    storyboard = build_storyboard(intervals, [source_durations[i] for i in base],
                                  seed=str(features.excerpt_start),
                                  no_bookend={base.index(i) for i in no_bookend if i in base})
    from .cinematic import Shot
    storyboard = [Shot(base[s.source_index], s.source_offset, s.duration) for s in storyboard]
    if signature_slots and len(base) < len(videos):
        from .signature import place_signature_shots
        storyboard = place_signature_shots(storyboard, source_durations, dict(signature_slots))
    # Picture follows the music: calm clips on quiet passages, moving clips on the loud ones.
    from . import look as look_mod
    motion_matched = False
    if os.getenv("CARLECOOL_MOTION_MATCH", "true").lower() in ("true", "1", "yes", "on") and len(storyboard) > 3:
        motion = [look_mod.motion_score(p) for p in videos]
        starts0 = [sum(sh.duration for sh in storyboard[:i]) for i in range(len(storyboard))]
        energies = [look_mod.shot_energy(features, a, sh.duration) for a, sh in zip(starts0, storyboard)]
        locked = {0, len(storyboard) - 1} | {i for i, sh in enumerate(storyboard) if sh.source_index in reserved}
        matched = look_mod.match_motion(storyboard, energies, motion, source_durations, locked)
        motion_matched = matched != storyboard
        storyboard = matched
    from .grading import cover_luts
    luts = cover_luts(cover, videos, work)
    level = analog / 100.0
    saturation = 1.0 - 0.25 * level
    contrast = 1.0 - 0.07 * level
    grain = int(round(6 * level))
    if look and grain:
        grain += int(look.get("grain_boost") or 0)  # 35 mm texture is part of both style worlds
    card = None
    card_seconds = 0.0
    if title_card is not None:
        from .titlecard import (COVER_CARD_SECONDS, TITLE_SECONDS, make_cover_card,
                                make_title_card)
        if cover is not None and os.getenv("CARLECOOL_COVER_ENDCARD", "true").lower() in ("true", "1", "yes", "on"):
            card = make_cover_card(Path(cover), title_card[0], title_card[1], width, height,
                                   work / "cover_card.png")
            card_seconds = COVER_CARD_SECONDS if card is not None else 0.0
        if card is None:
            card = make_title_card(title_card[0], title_card[1], width, height, work / "title_card.png")
            card_seconds = TITLE_SECONDS
    card_start = max(0.0, length - card_seconds) if card is not None else None
    # Owner feedback: the cover belongs at the END only. The loop stays seamless through the
    # audio crossfade and a hard cut on the downbeat back to shot 1; the opening cover
    # bridge is opt-in (CARLECOOL_LOOP_BRIDGE=on).
    loop_bridge = (card is not None and card.name == "cover_card.png" and length > 6
                   and os.getenv("CARLECOOL_LOOP_BRIDGE", "off").lower() in ("true", "1", "yes", "on"))
    # Cover frame for Instagram/TikTok: the end card fully faded in, just before the loop.
    cover_frame_ms = int(round(max(0.0, length - 0.5) * 1000)) if card is not None else None
    # Content-aware 9:16 reframing for landscape sources (decoded once per source).
    from . import reframe
    dims = []
    for path in videos:
        try:
            dims.append(probe_dimensions(path))
        except (RuntimeError, ValueError, subprocess.SubprocessError):
            dims.append((0, 0))
    samples: dict[int, object] = {}
    reframed = 0
    framed = 0
    files = []
    shot_start = 0.0
    starts = [sum(s.duration for s in storyboard[:i]) for i in range(len(storyboard))]
    shot_look = look_mod.plan_look(look, features, starts, [s.duration for s in storyboard],
                                   seed=str(features.excerpt_start))
    for item in shot_look:  # frame-exact transitions keep the cuts on the beat grid
        item["dissolve_in"] = round(item["dissolve_in"] * FPS) / FPS
    leak = None
    if any(item["leak"] for item in shot_look):
        leak = look_mod.make_light_leak(width, height, work / "light_leak.png")
    fps_cache: dict[int, float] = {}
    slowed = 0
    punched = 0
    leaks = 0
    for index, shot in enumerate(storyboard):
        styling = shot_look[index]
        source = videos[shot.source_index]
        src_w, src_h = dims[shot.source_index]
        smart = None
        # Low-resolution landscape (e.g. 640x480 archive film): a 9:16 crop would be
        # upscaled ~4x and look mushy. Show it full-width over a blurred copy instead.
        if src_w > src_h > 0 and width / max(1.0, src_h * 9 / 16) > FRAMED_UPSCALE_LIMIT:
            smart = [f"split=2[fa{index}][fb{index}];"
                     f"[fa{index}]scale={width}:{height}:force_original_aspect_ratio=increase,"
                     f"crop={width}:{height},boxblur=24:2,eq=brightness=-0.12:saturation=0.8[bg{index}];"
                     f"[fb{index}]scale={width}:-2:flags=lanczos[fg{index}];"
                     f"[bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2"]
            framed += 1
        if smart is None and os.getenv("CARLECOOL_SMART_CROP", "true").lower() in ("true", "1", "yes", "on") \
                and reframe.needs_reframe(src_w, src_h):
            try:
                if shot.source_index not in samples:
                    samples[shot.source_index] = reframe.FrameSamples.decode(source, src_w, src_h)
                crop = reframe.plan_crop(samples[shot.source_index], shot.source_offset, shot.duration)
                smart = [reframe.crop_filter(crop, src_h, shot.duration),
                         f"scale={width}:{height}:flags=lanczos"]
                reframed += 1
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                print("Smart crop unavailable; centre crop:", type(exc).__name__)
        chain = list(smart or [f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
                               f"crop={width}:{height}"])
        if styling["punch_in"] and not (src_w > src_h > 0 and chain and chain[0].startswith("split")):
            # Rubin: peaks get closer, not busier.
            chain += [f"crop=iw*0.9:ih*0.9", f"scale={width}:{height}:flags=lanczos"]
            punched += 1
        chain.append("setsar=1")
        speed = 1.0
        if styling["slowmo"] > 1.0:
            if shot.source_index not in fps_cache:
                fps_cache[shot.source_index] = look_mod.probe_fps(source)
            speed = look_mod.slowmo_factor(styling["slowmo"], fps_cache[shot.source_index], FPS)
            if speed > 1.0:
                chain.append(f"setpts={speed}*PTS")
                slowed += 1
        chain.append(f"fps={FPS}")
        lut = luts[shot.source_index]
        if lut is not None:
            chain.append(f"lut3d=file={_filter_path(lut)}:interp=tetrahedral")
        chain.append(f"eq=saturation={saturation:.3f}:contrast={contrast:.3f}:gamma=1.015"
                     + (f":brightness={styling['brightness']:.4f}" if styling["brightness"] else ""))
        chain.extend(style_grade or [])
        if grain:
            chain.append(f"noise=alls={grain}:allf=t")
        # Outgoing shot runs on under the next shot's dissolve (total length unchanged).
        tail = shot_look[index + 1]["dissolve_in"] if index + 1 < len(storyboard) else 0.0
        part = work / f"clip_{index:03}.mp4"
        # Seek before input; -stream_loop is only a last resort for sources shorter than the shot.
        needed = (shot.duration + tail) / speed
        loop = ["-stream_loop", "-1"] if source_durations[shot.source_index] - shot.source_offset < needed else []
        inputs = [*loop, "-ss", f"{shot.source_offset:.3f}", "-i", str(source)]
        shot_end = shot_start + shot.duration
        overlays = []  # (input args, per-input filter, overlay options)
        if styling["leak"] and leak is not None:
            # Warm light leak blooming in and out at the start of the shot (Lana).
            flip = "hflip," if index % 2 else ""
            overlays.append((["-loop", "1", "-framerate", str(FPS), "-i", str(leak)],
                             f"format=rgba,{flip}fade=t=in:st=0:d=0.25:alpha=1,fade=t=out:st=0.45:d=0.5:alpha=1",
                             "overlay=0:0"))
            leaks += 1
        if index == 0 and loop_bridge:
            # Seamless loop: the Reel ends on the cover card and opens on it too, dissolving
            # into the first shot — the repeat on TikTok/Instagram shows no jump or gap.
            overlays.append((["-loop", "1", "-framerate", str(FPS), "-i", str(card)],
                             f"format=rgba,fade=t=out:st=0.04:d={LOOP_BRIDGE_SECONDS:.2f}:alpha=1",
                             "overlay=0:0"))
        if card_start is not None and shot_end + tail > card_start + 1e-3:
            # Title card fades in over the last ~2 s, after grain so the text stays crisp.
            local = max(0.0, card_start - shot_start)
            fade = "" if card_start < shot_start - 1e-3 else f",fade=t=in:st={local:.3f}:d=0.35:alpha=1"
            overlays.append((["-loop", "1", "-framerate", str(FPS), "-i", str(card)],
                             f"format=rgba{fade}", f"overlay=0:0:enable='gte(t,{local:.3f})'"))
        if overlays:
            graph = [f"[0:v]{','.join(chain)}[b0]"]
            for k, (args, prep, how) in enumerate(overlays, start=1):
                inputs += args
                graph.append(f"[{k}:v]{prep}[o{k}]")
                graph.append(f"[b{k - 1}][o{k}]{how}[b{k}]")
            graph.append(f"[b{len(overlays)}]format=yuv420p[out]")
            video_args = ["-filter_complex", ";".join(graph), "-map", "[out]"]
        else:
            video_args = ["-vf", ",".join(chain + ["format=yuv420p"])]
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-frames:v", str(max(1, round((shot.duration + tail) * FPS))),
            *video_args,
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-tune", "grain" if grain else "film", "-profile:v", "high",
            "-maxrate", "16M", "-bufsize", "24M",
            "-g", str(FPS * 2), "-r", str(FPS), "-video_track_timescale", str(FPS * 1000), str(part),
        ])
        shot_start = shot_end
        files.append(part)
    concat_path = work / "concat.txt"
    # FFmpeg concat demuxer does not parse shell quoting; enforce simple generated filenames.
    concat_path.write_text("".join(f"file '{p.name}'\n" for p in files), encoding="utf-8")
    video_only = work / "joined.mp4"
    dissolves = [item["dissolve_in"] for item in shot_look]
    if any(d > 0 for d in dissolves):
        graph, label = look_mod.join_graph([s.duration for s in storyboard], dissolves)
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              *[arg for f in files for arg in ("-i", str(f))],
              "-filter_complex", graph, "-map", f"[{label}]", "-an",
              "-c:v", "libx264", "-preset", "medium", "-crf", "18",
              "-tune", "grain" if grain else "film", "-profile:v", "high",
              "-maxrate", "16M", "-bufsize", "24M", "-g", str(FPS * 2), "-r", str(FPS),
              "-video_track_timescale", str(FPS * 1000), str(video_only)])
    else:
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
              "-i", str(concat_path), "-c", "copy", str(video_only)])
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_only), "-i", str(audio),
        "-filter_complex", loop_audio_graph(audio, features.excerpt_start, length),
        "-map", "0:v:0", "-map", "[a]", "-t", f"{length:.3f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
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
            "title_card": card is not None,
            "cover_endcard": card is not None and card.name == "cover_card.png",
            "cover_frame_ms": cover_frame_ms,
            "motion_matched": motion_matched,
            "seamless_loop": {"audio_crossfade": round(min(LOOP_CROSSFADE, features.excerpt_start, length / 4), 3),
                              "cover_bridge": loop_bridge},
            "smart_cropped_shots": reframed,
            "dissolves": sum(1 for d in dissolves if d > 0), "slowmo_shots": slowed,
            "light_leaks": leaks, "punch_ins": punched,
            "framed_shots": framed,
            "signature_shots": {role: sum(1 for sh in storyboard if sh.source_index == idx)
                                for role, idx in (signature_slots or {}).items()},
            "compressed_for_email": compressed_for_email,
            "edit_plan": [{"source_index": s.source_index,
                           "source_offset": s.source_offset,
                           "duration": s.duration} for s in storyboard]}
