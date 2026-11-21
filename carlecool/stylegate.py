"""Style and content gate for EVERY stock clip (not only the signature shots).

Reel #35 ("chronocyte horizon") showed what slips through when clips are only ranked by
cover colours: an animated "anthropomorphic fruit car chase", modern Porsche GT3 /
Turbo S, a Mexico City street, a "Hi there" sign. Two checks, before any download:

1. Title/tag words: animation, cartoon, 3D/CGI/AI renders, modern supercars and model
   codes, exotic travel places that break the European/Americana world.
2. OpenCLIP on the thumbnail: best "unwanted" prompt (cartoon, render, text sign, modern
   sports car, tropical travel …) versus best "wanted" prompt of the style world. A clip
   is rejected when an unwanted prompt wins by MARGIN.

No model → only the word check. Never raises.
"""
from __future__ import annotations

import re

BLOCK_WORDS = (
    # animation / synthetic looks
    "anthropomorphic", "animated", "animation", "cartoon", "3d", "cgi", "render", "rendered",
    "ai generated", "ai-generated", "generative", "illustration", "motion graphic", "emoji",
    "smiley", "mascot", "claymation", "toy car", "lego", "pixel art", "anime",
    # modern supercars / model codes (owner: classic Porsche 993, classic Defender)
    "gt3", "gt2", "turbo s", "taycan", "cayenne", "macan", "panamera", "992", "991", "tesla",
    "lamborghini", "ferrari", "mclaren", "bugatti", "electric car", "ev charging",
    # places outside the European-city × Americana world
    "mexico", "volcano", "jungle", "safari", "temple", "pagoda", "mosque", "dubai", "bali",
    "thailand", "india", "sweden", "iceland", "tokyo",
    # signage with words, office/ad looks
    "hi there", "welcome sign", "office", "business meeting", "advertisement", "product shot",
)
UNWANTED = (
    "a cartoon or an animated film", "a 3d computer rendering", "an ai generated cartoon character",
    "a car with a cartoon face", "a sign with large written words", "a modern sports car or supercar",
    "a tropical volcano or jungle", "a busy street in latin america", "an office or a business meeting",
    "a product advertisement", "a screen with text or a user interface",
    "a modern porsche 911 from the 2020s with wide wheels",
)
WANTED = {
    "lana": ("young friends together outdoors at golden hour", "a neon motel or diner sign at dusk",
             "an american flag waving", "a classic air-cooled porsche 911 from the 1990s",
             "a classic land rover defender",
             "a road trip on an empty american highway", "palm trees and a pale summer sky",
             "a skateboarder on a street", "a woman in natural light", "a vintage color home movie",
             "a city street at night with lights", "a sunset over a calm landscape"),
    "rubin": ("young friends sitting together in silence", "an empty parking lot at dusk",
              "an american flag on a fence", "a classic land rover defender",
              "a classic air-cooled porsche 911 from the 1990s", "a neon diner or motel sign at night",
              "an american diner interior", "palm trees against a pale sky",
              "a basketball court in evening light", "a quiet street in a european city",
              "a skateboarder seen from behind", "a woman by a window in natural light",
              "a vintage color home movie", "an empty road under an overcast sky", "a calm landscape"),
}
MARGIN = 0.0


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (text or "").lower()) + " "


def blocked_words(video) -> str | None:
    """The first block word found in title/tags (whole words), else None."""
    text = _norm(" ".join([getattr(video, "title", "") or "", *(getattr(video, "tags", ()) or ())]))
    for word in BLOCK_WORDS:
        if _norm(word) in text:
            return word
    return None


def clip_verdicts(images, world: str | None, clip) -> list[tuple[float, str] | None]:
    """Per image: (wanted − unwanted similarity, best unwanted prompt); None if unscored."""
    if clip is None or not images:
        return [None] * len(images)
    try:
        import torch
        from PIL import Image
        model, preprocess, tokenizer = clip
        wanted = WANTED.get(world or "", WANTED["lana"])
        prompts = [f"a photo of {p}" for p in wanted] + list(UNWANTED)
        with torch.no_grad():
            text = torch.nn.functional.normalize(model.encode_text(tokenizer(prompts)), dim=-1)
            out = []
            for image in images:
                if image is None:
                    out.append(None)
                    continue
                with Image.open(image) as img:
                    v = torch.nn.functional.normalize(
                        model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)
                sims = (v @ text.T)[0].tolist()
                good, bad = sims[:len(wanted)], sims[len(wanted):]
                worst = max(range(len(bad)), key=lambda k: bad[k])
                out.append((max(good) - bad[worst], UNWANTED[worst]))
        return out
    except Exception as exc:
        print("Style gate unavailable:", type(exc).__name__)
        return [None] * len(images)


def rejected(verdict: tuple[float, str] | None) -> bool:
    return verdict is not None and verdict[0] < MARGIN
