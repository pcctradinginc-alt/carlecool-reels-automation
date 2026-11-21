"""Fail-closed, frame-based style admission for the existing v4 Reel renderer.

This is an intentionally conservative visual *gate*, not a claim that OpenCLIP can
recognize geography or guarantee editorial taste. No acceptable frames, no Reel.
All sources (stock, signatures, archives and owned media) pass the same gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re

WORLDS = ("lana", "rubin")

# Describe the desired *photographic content*, not just the colour palette.
POSITIVE = {
    "lana": (
        "an authentic cinematic 35mm photograph of a Californian desert at golden hour",
        "a nostalgic film photograph of palm trees at sunset on the California coast",
        "a faded 1970s American roadside motel in the desert photographed on film",
        "an atmospheric photograph of an old American diner at dusk",
        "a real vintage 1960s American convertible parked beside a desert motel",
        "a natural candid documentary photograph of young friends in summer sunlight",
        "a genuine grainy Super 8 film photograph of a woman in a sunlit field",
        "a real 1990s California skateboarder filmed with an analog camera",
        "a cinematic film photograph of an empty Pacific ocean beach at sunset",
        "an artistic photographic closeup of a faded American flag and vintage textures",
    ),
    "rubin": (
        "an authentic documentary photograph of hands on an analog recording console",
        "a natural cinematic photograph of a minimalist wooden music recording studio",
        "a still meditative film photograph of the ocean horizon in soft natural light",
        "a real documentary photograph of a vinyl turntable and tape machine",
        "a minimalist cinematic photograph of sunlight and shadows in an empty quiet room",
        "a candid documentary film photograph of friends sitting quietly outdoors",
        "a real photograph of peaceful trees and filtered afternoon sunlight",
        "an intimate photograph of a musician playing an acoustic instrument",
        "a close-up documentary photograph of a hand operating an analog sampler",
        "a restrained black and white documentary photograph of skateboard wheels",
    ),
}

# Hard negatives apply to BOTH worlds, irrespective of cover colour.
HARD_NEGATIVES = (
    "a bright colorful cartoon or anime with illustrated characters",
    "smiling emoji faces driving cartoon racing cars in a computer animation",
    "a 3D rendered racing game with cute smiley characters and toy automobiles",
    "a computer generated animation of emoji faces and stickers",
    "an illustrated comic strip of vehicles racing on a road",
    "a CGI video game race with synthetic cars and glowing effects",
    "modern everyday cars driving on a generic German countryside road",
    "ordinary European rural road traffic with modern hatchbacks and sedans",
    "a dashcam film of cars on a German highway or suburban street",
    "multiple modern cars driving along a green country lane",
    "race cars speeding or drifting around a race track",
    "a busy modern highway with trucks and traffic",
    "a generic glossy commercial advertisement with artificial studio lighting",
    "an influencer selfie video with text overlays and cartoon stickers",
    "an artificial computer generated 3D character with plastic skin",
    "video with large subtitles, infographic graphics or a visible logo",
    "a generic digitally animated abstract background with bright geometric shapes",
)

# Text-based blocklist is extra protection; it is NOT a substitute for checking frames.
_BLOCKED_METADATA = re.compile(
    r"\b(?:cartoons?|animes?|emojis?|smileys?|animations?|"
    r"racing|racecars?|race\s+cars?|drifting|gameplay|video\s*games?|"
    r"highway\s+traffic|road\s+traffic|autobahn|landstra(?:ss|ß)e|"
    r"motorway|3d\s+renders?|cgi\s+animation)\b",
    flags=re.IGNORECASE,
)
MIN_POSITIVE = 0.21
MIN_MARGIN = 0.018
FRAMES_PER_CLIP = 5


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str
    lowest_positive: float = 0.0
    closest_margin: float = 0.0


def enabled() -> bool:
    """Strict mode is activated for daily production in its GitHub workflow."""
    return os.getenv("CARLECOOL_VISUAL_STRICT", "false").strip().lower() in {"1", "true", "yes", "on"}


def judge_frames(frame_scores, *, positive_count: int, minimum: float = MIN_POSITIVE,
                 margin: float = MIN_MARGIN) -> Decision:
    """All sampled frames must individually pass; a good average cannot hide a cartoon."""
    if not frame_scores:
        return Decision(False, "no_decodable_frames")
    min_pos, min_margin = float("inf"), float("inf")
    for frame_index, scores in enumerate(frame_scores):
        values = [float(s) for s in scores]
        if (positive_count <= 0 or len(values) <= positive_count
                or not all(math.isfinite(v) for v in values)):
            return Decision(False, f"invalid_scores_frame_{frame_index}")
        positive = max(values[:positive_count])
        negative = max(values[positive_count:])
        delta = positive - negative
        min_pos = min(min_pos, positive)
        min_margin = min(min_margin, delta)
        if positive < minimum:
            return Decision(False, f"off_style_frame_{frame_index}", round(min_pos, 4), round(min_margin, 4))
        if delta < margin:
            return Decision(False, f"negative_match_frame_{frame_index}", round(min_pos, 4), round(min_margin, 4))
    return Decision(True, "passed", round(min_pos, 4), round(min_margin, 4))


def _model_scorer(world: str):
    """Model load is mandatory; optional CLIP failure must never become palette fallback."""
    from .semantic import load_clip, _frame
    from .render import probe_duration

    clip = load_clip()
    if clip is None:
        raise RuntimeError("Strict visual gate requires the free OpenCLIP model; model unavailable")
    try:
        import torch
        model, preprocess, tokenizer = clip
        labels = [f"A real photographic frame of {s}." for s in POSITIVE[world]]
        labels.extend(f"An image of {s}." for s in HARD_NEGATIVES)
        with torch.no_grad():
            reference = torch.nn.functional.normalize(
                model.encode_text(tokenizer(labels)), dim=-1)

        def score(path: Path) -> Decision:
            duration = probe_duration(path)
            if not math.isfinite(duration) or duration < 1.0:
                return Decision(False, "undecodable_or_too_short")
            # Include the end: hidden cartoons and transitions must not pass on one thumbnail.
            timestamps = [max(0.1, min(duration - 0.1, duration * f))
                          for f in (0.1, 0.3, 0.5, 0.7, 0.9)]
            with torch.no_grad():
                frames = torch.cat([
                    model.encode_image(preprocess(_frame(path, second)).unsqueeze(0))
                    for second in timestamps
                ], dim=0)
                frames = torch.nn.functional.normalize(frames, dim=-1)
                scores = (frames @ reference.T).tolist()
            return judge_frames(scores, positive_count=len(POSITIVE[world]))

        return score
    except Exception as exc:
        raise RuntimeError("Strict visual model initialization failed; refusing unverified media") from exc


def gate_clips(paths: list[Path], videos: list, world: str, *,
               reel_length: float, scorer=None) -> tuple[list[int], dict]:
    """Return approved source indices and audit info, or raise without rendering.

    The injectable scorer exists only for deterministic, offline unit tests.
    Production always loads a real OpenCLIP encoder. An exception is fatal.
    """
    if world not in WORLDS:
        raise RuntimeError("Strict visual mode requires exactly one of lana/rubin")
    if not paths or len(paths) != len(videos):
        raise RuntimeError("Strict visual mode received no consistent footage")
    scorer = _model_scorer(world) if scorer is None else scorer
    kept, rejected, approved = [], [], []
    for index, (path, video) in enumerate(zip(paths, videos)):
        source = str(getattr(video, "source", "")).lower()
        identifier = str(getattr(video, "id", index))
        metadata = " ".join([
            str(getattr(video, "title", "") or ""),
            " ".join(getattr(video, "tags", ()) or ()),
        ])
        if source == "ai":
            decision = Decision(False, "unverified_ai_source_disabled")
        elif _BLOCKED_METADATA.search(metadata):
            decision = Decision(False, "blocked_source_metadata")
        else:
            try:
                decision = scorer(Path(path))
            except Exception as exc:
                # Corrupt video or inaccessible decoder must not be silently admitted.
                decision = Decision(False, f"inspection_failed_{type(exc).__name__}")
        if decision.approved:
            kept.append(index)
            approved.append({"id": identifier, "source": source,
                             "minimum_style_score": decision.lowest_positive,
                             "minimum_margin": decision.closest_margin})
        else:
            rejected.append({"id": identifier, "source": source, "reason": decision.reason})
    # Avoid a film of repeated scraps when most footage has failed its style gate.
    required = max(4, math.ceil(float(reel_length) / 5.0))
    if len(kept) < required:
        raise RuntimeError(
            f"Strict visual gate: only {len(kept)}/{len(paths)} clips approved "
            f"(minimum {required}); refusing to render a low-quality Reel. "
            f"Rejected: {rejected}"
        )
    return kept, {"mode": "strict", "world": world, "model": "OpenCLIP ViT-B-32",
                  "frames_per_clip": FRAMES_PER_CLIP, "required_clips": required,
                  "approved": approved, "rejected": rejected}
