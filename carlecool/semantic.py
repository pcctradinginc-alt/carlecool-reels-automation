"""Optional CPU OpenCLIP semantic matching of public cover and licensed video frames.

Model weights are public third-party data, never uploaded artist assets.
For free runners this is strictly opt-in: CARLECOOL_SEMANTIC=on and installed
open_clip_torch/Pillow/PyTorch. Failure returns None; palette path remains.
"""
from __future__ import annotations

import io
import math
import os
from pathlib import Path
import subprocess

import numpy as np

DESCRIPTIONS = (
    "cinematic empty California highway at sunset, nostalgic Americana",
    "quiet sunlit ocean, waves and sandy coast, meditative nature",
    "warm minimalist recording studio, analog instruments and wooden furniture",
    "vintage film texture, motel sign, palm trees and summer nostalgia",
    "skateboarder on California concrete, handheld fisheye video",
    "dramatic neon reflections of a city at night",
    "serene forest, sunlight through green trees and still water",
    "close up of hands playing synthesizer knobs, cassette or vinyl records",
)


def _frame(path: Path, seconds: float) -> "PIL.Image.Image":
    from PIL import Image
    cmd = ["ffmpeg", "-v", "error"]
    if seconds > 0:
        cmd += ["-ss", str(seconds)]
    cmd += ["-i", str(path), "-frames:v", "1", "-vf", "scale=256:256:force_original_aspect_ratio=decrease",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    p = subprocess.run(cmd, capture_output=True, check=True, timeout=30)
    with Image.open(io.BytesIO(p.stdout)) as img:
        return img.convert("RGB")


def score_semantic(cover: Path, videos: list[Path], *, style: str = "",
                   model=None, preprocess=None, tokenizer=None,
                   sample_seconds=(0.5, 2.0)) -> dict | None:
    """Rank videos by cover similarity and narrative style, with multiple frames.

    An injected model/preprocess/tokenizer allows deterministic offline tests.
    Scores are relative and do not establish license/quality/actual engagement.
    """
    if not videos:
        return None
    try:
        import torch
        if model is None:
            import open_clip
            torch.set_num_threads(min(2, torch.get_num_threads()))
            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="laion2b_s34b_b79k", device="cpu")
            tokenizer = open_clip.get_tokenizer("ViT-B-32")
        model.eval()
        with torch.no_grad():
            cover_embedding = model.encode_image(preprocess(_frame(cover, 0)).unsqueeze(0))
            cover_embedding = torch.nn.functional.normalize(cover_embedding, dim=-1)
            captions = [f"A cinematic frame of {item}." for item in DESCRIPTIONS]
            text_embeddings = model.encode_text(tokenizer(captions))
            text_embeddings = torch.nn.functional.normalize(text_embeddings, dim=-1)
            cover_tags = (cover_embedding @ text_embeddings.T)[0]
            # The cover's closest themes anchor the edit; the fixed preset
            # acts only as an additional weak prompt, never overrides the cover.
            top = torch.topk(cover_tags, min(2, len(DESCRIPTIONS))).indices
            target = torch.nn.functional.normalize(
                0.8 * cover_embedding +
                0.2 * torch.nn.functional.normalize(text_embeddings[top].mean(0, keepdim=True), dim=-1),
                dim=-1,
            )
            scores = []
            for path in videos:
                vectors = []
                for second in sample_seconds[:3]:
                    try:
                        v = model.encode_image(preprocess(_frame(path, max(0.0, second))).unsqueeze(0))
                        vectors.append(torch.nn.functional.normalize(v, dim=-1))
                    except (OSError, ValueError, subprocess.SubprocessError):
                        continue
                if not vectors:
                    scores.append(-1.0)
                    continue
                similarity = float((torch.cat(vectors, dim=0) @ target.T).mean().item())
                scores.append(round(max(-1.0, min(1.0, similarity)), 5))
            if not any(s > -1 for s in scores):
                return None
            ranking = sorted(range(len(videos)), key=lambda i: (-scores[i], i))
            themes = [DESCRIPTIONS[int(x)] for x in top.tolist()]
            return {"order": ranking, "scores": [scores[i] for i in ranking],
                    "themes": themes, "model": "OpenCLIP ViT-B-32 LAION-2B"}
    except (ImportError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("Optional semantic scoring unavailable:", type(exc).__name__)
        return None
