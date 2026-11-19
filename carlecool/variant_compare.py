"""Make and compare three private local previews, without publishing or emailing.

Usage:
 python -m carlecool.variant_compare --audio owned.mp3 --video licensed1.mp4
   --video licensed2.mp4 --output output/variants

Only use owned tracks and licensed clips. Generated media never enter GitHub
artifacts or public issues. Scores are technical, NOT predicted virality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .analysis import analyze_audio
from .render import render_reel

VARIANTS = (
    ("americana_cinema", "slow", 85),
    ("rubin_minimal", "slow", 45),
    ("electronic_cut", "fast", 65),
)


def compare(audio: Path, videos: list[Path], output: Path, *,
            length: int = 20, genre: str = "") -> dict:
    if not audio.is_file() or not videos or not all(p.is_file() for p in videos):
        raise FileNotFoundError("Owned audio and licensed footage must exist")
    if not 8 <= length <= 30:
        raise ValueError("Compare length must be between 8 and 30 seconds")
    output.mkdir(parents=True, exist_ok=True)
    features = analyze_audio(str(audio), length, genre)
    results = []
    for label, pace, analog in VARIANTS:
        # Use an isolated folder because FFmpeg uses fixed intermediate names.
        folder = output / label
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "preview.mp4"
        details = render_reel(audio, videos, features, target, features.reel_length or length,
                              pace=pace, analog=analog)
        edit_plan = details["edit_plan"]
        unique_sources = len({shot["source_index"] for shot in edit_plan})
        boundaries = []
        elapsed = 0.
        for shot in edit_plan[:-1]:
            elapsed += shot["duration"]
            boundaries.append(elapsed)
        nearby_events = sum(any(abs(t-e) <= .65 for e in features.structure_events)
                            for t in boundaries)
        # Diagnostic, NOT an aesthetic grade or virality prediction.
        results.append({"name": label, "pace": pace, "analog": analog,
                        "diagnostics": {
                            "unique_sources": unique_sources,
                            "source_count": len(videos),
                            "structural_cut_hits": nearby_events,
                            "total_cuts": len(boundaries)},
                        "file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        "duration": details["duration"], "scenes": details["scenes"],
                        "resolution": details["resolution"]})
    report = {"comparison_type": "technical_only_not_predicted_virality",
              "source_count": len(videos), "variants": results,
              "recommended_selection": "human_review"}
    (output / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--video", action="append", type=Path, required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--length", type=int, default=20)
    args = parser.parse_args()
    report = compare(args.audio, args.video, args.output, length=args.length)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
