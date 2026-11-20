"""Creative v5: FREE, opt-in, fail-closed cover-to-storyboard direction.

Uses the existing local OpenCLIP checkpoint and the EXISTING three stock-search
lanes. No generative/paid API, no uploads to a vision service, no posting logic.
All visual labels are model estimates requiring human review, not guarantees.
"""
from __future__ import annotations

import os
from pathlib import Path

ROLE_QUERIES = {
    "skater": "skateboarder performing street tricks",
    "woman": "adult woman cinematic portrait",
}
# Prompt vocabulary intentionally short: no celebrity likenesses or branded imagery.
COVER_MOTIFS = {
    "americana": (
        "A rider on a horse carrying an American flag across an open landscape",
        "A cowboy riding a horse on a dusty road in America",
    ),
    "pastel_cosmos": (
        "A pastel pink and lavender planet floating in outer space",
        "A dreamy colourful planet against a soft cosmic sky",
    ),
    "analog_studio": (
        "A vintage analogue music recording studio with a synthesizer",
        "A closeup photograph of a vinyl record, cassette tapes and music equipment",
    ),
    "night_city": (
        "A cinematic photograph of a rainy city street with night lights",
        "A neon lit street at night with blue and purple reflections",
    ),
    "coastal_zen": (
        "A calm quiet beach with soft sky and ocean horizon",
        "A minimalist white room with daylight and natural textures",
    ),
}
COVER_STOCK = {
    "americana": "California desert road sunset",
    "pastel_cosmos": "pastel clouds sky",
    "analog_studio": "analog recording studio",
    "night_city": "neon city night reflections",
    "coastal_zen": "ocean coastline sunrise",
}
# Never infer attractiveness or age from appearance beyond a generic adult-person
# visual category. Exact role selection is a reviewable artistic interpretation.
ROLE_PROMPTS = {
    "skater": (
        ("An adult skateboarder riding a skateboard in a skatepark",
         "A person performing a skateboarding trick on a skateboard",
         "A street skateboarder skating on concrete"),
        ("An empty skatepark without people",
         "A person walking down a street without a skateboard",
         "A close-up of a skateboard lying on the ground"),
    ),
    "woman": (
        ("A cinematic portrait of a grown woman standing outdoors",
         "An adult woman with stylish clothing in a music video",
         "A woman standing in a beautiful landscape"),
        ("An empty landscape without people",
         "A male person standing in a city",
         "An empty room with furniture and no people"),
    ),
}
MIN_POSITIVE = 0.20  # conservative initial heuristic, NOT a calibrated probability
MIN_MARGIN = 0.018


def enabled() -> bool:
    return os.getenv("CARLECOOL_CREATIVE_V5", "off").strip().lower() == "on"


def direction_from_scores(scores: dict[str, float], palette: dict) -> dict:
    """Choose a conservative cover motif, then use colour as a safe fallback."""
    ordered = sorted(((float(value), name) for name, value in scores.items()
                      if name in COVER_MOTIFS), reverse=True)
    best = ordered[0] if ordered else (0.0, "")
    second = ordered[1][0] if len(ordered) > 1 else 0.0
    if best[0] >= 0.23 and best[0] - second >= 0.012:
        style, basis = best[1], "openclip"
    elif palette.get("saturation", 1) < 0.17 and palette.get("brightness", 0) > 0.55:
        style, basis = "coastal_zen", "palette"
    elif palette.get("warmth", 0) > 0.04:
        style, basis = "americana", "palette"
    elif palette.get("brightness", 1) < 0.33:
        style, basis = "night_city", "palette"
    else:
        style, basis = "analog_studio", "palette"
    return {"style": style, "basis": basis, "cover_query": COVER_STOCK[style],
            "palette": {key: float(palette.get(key, 0))
                        for key in ("brightness", "saturation", "warmth", "greenness")},
            "motif_scores": {key: round(float(value), 4)
                             for key, value in scores.items() if key in COVER_MOTIFS}}


def analyze_cover(cover: Path) -> dict:
    """Local OpenCLIP image-vs-text recognition, with existing palette fallback."""
    from .curation import palette_traits
    from .semantic import load_clip, _frame
    palette = palette_traits(cover)
    loaded = load_clip()
    if loaded is None:
        raise RuntimeError("Creative v5 requires the existing free OpenCLIP model; "
                           "no cover analysis available. Classic mode is unaffected.")
    import torch
    model, preprocess, tokenizer = loaded
    texts = [(name, phrase) for name, phrases in COVER_MOTIFS.items() for phrase in phrases]
    with torch.no_grad():
        image = model.encode_image(preprocess(_frame(cover, 0)).unsqueeze(0))
        image = torch.nn.functional.normalize(image, dim=-1)
        embeddings = model.encode_text(tokenizer([phrase for _, phrase in texts]))
        embeddings = torch.nn.functional.normalize(embeddings, dim=-1)
        similarities = (image @ embeddings.T)[0].tolist()
    scores = {name: max(float(similarities[i]) for i, (motif, _) in enumerate(texts)
                        if motif == name) for name in COVER_MOTIFS}
    return direction_from_scores(scores, palette)


def search_phrases(direction: dict) -> list[str]:
    """Exactly three existing stock search lanes: woman, skater, cover."""
    style = direction["style"]
    if style not in COVER_STOCK:
        raise ValueError("Unsupported Creative v5 style")
    return [ROLE_QUERIES["woman"], ROLE_QUERIES["skater"], COVER_STOCK[style]]


def _role_hint(video) -> str | None:
    query = (getattr(video, "query", "") or "").lower()
    if query == ROLE_QUERIES["woman"].lower():
        return "woman"
    if query == ROLE_QUERIES["skater"].lower():
        return "skater"
    return None


def prioritize_candidates(candidates: list, *, role_budget: int = 2) -> list:
    """Keep two tries per signature before aesthetic candidates, without new API calls.

    Search-query provenance is only a discovery hint. Real frames MUST pass the
    OpenCLIP signature verification before the video may leave private preview.
    """
    result = []
    remaining = list(candidates)
    for role in ("woman", "skater"):
        matching = [v for v in remaining if _role_hint(v) == role]
        matching.sort(key=lambda v: (not bool(getattr(v, "vertical", False)),
                                     -float(getattr(v, "score", 0))))
        chosen = matching[:role_budget]
        result.extend(chosen)
        chosen_ids = {id(v) for v in chosen}
        remaining = [v for v in remaining if id(v) not in chosen_ids]
    return result + remaining


def is_role_candidate(video) -> bool:
    return _role_hint(video) is not None


def choose_verified_roles(scores: list[dict], *,
                          min_positive: float = MIN_POSITIVE,
                          min_margin: float = MIN_MARGIN) -> dict:
    """Select DISTINCT real-video sources for both signatures.

    Scores are {role: (max_positive_cosine, max_negative_cosine)} per clip.
    A threshold is a cautious heuristic, not a guarantee about video content.
    """
    eligible = {}
    for role in ("woman", "skater"):
        options = []
        for idx, item in enumerate(scores):
            values = item.get(role)
            if not values or len(values) != 2:
                continue
            positive, negative = float(values[0]), float(values[1])
            margin = positive - negative
            if positive >= min_positive and margin >= min_margin:
                options.append((margin, positive, idx))
        eligible[role] = sorted(options, reverse=True)
    pairs = [(w[0] + s[0], w, s) for w in eligible["woman"]
             for s in eligible["skater"] if w[2] != s[2]]
    if not pairs:
        missing = ", ".join(role for role in ("woman", "skater") if not eligible[role])
        detail = missing or "two distinct clips"
        raise RuntimeError("Creative v5 safety stop: no confidently verified "
                           + detail + " in licensed clips; NO private review or publication."
                           " Add rights-cleared portrait footage or use classic mode.")
    _, woman, skater = max(pairs)
    return {"woman": {"index": woman[2], "score": round(woman[0], 4)},
            "skater": {"index": skater[2], "score": round(skater[0], 4)}}


def verify_signatures(paths: list[Path], selected: list) -> dict:
    """Read actual video frames locally; do not trust provider tags or thumbnails."""
    if len(paths) != len(selected):
        raise ValueError("Creative v5 footage/provenance list mismatch")
    from .semantic import load_clip, _frame
    loaded = load_clip()
    if loaded is None:
        raise RuntimeError("Creative v5 cannot verify both signature subjects: OpenCLIP unavailable")
    import torch
    model, preprocess, tokenizer = loaded
    keys = ("woman", "skater")
    prompts = [prompt for role in keys for group in ROLE_PROMPTS[role]
               for prompt in group]
    with torch.no_grad():
        text = model.encode_text(tokenizer(prompts))
        text = torch.nn.functional.normalize(text, dim=-1)
        scores = []
        for path in paths:
            # A query match alone is never sufficient: inspect actual frames.
            images = []
            for second in (0.5, 1.5, 2.5):
                try:
                    images.append(preprocess(_frame(path, second)))
                except (OSError, ValueError, RuntimeError):
                    continue
            if not images:
                scores.append({})
                continue
            frames = model.encode_image(torch.stack(images))
            frames = torch.nn.functional.normalize(frames, dim=-1)
            sims = frames @ text.T
            record = {}
            cursor = 0
            for role in keys:
                positives, negatives = ROLE_PROMPTS[role]
                p = len(positives)
                n = len(negatives)
                # Select one frame that genuinely contains the subject; for
                # each frame compare its strongest positive and negative cue.
                frame_positive = sims[:, cursor:cursor + p].max(dim=1).values
                frame_negative = sims[:, cursor + p:cursor + p + n].max(dim=1).values
                margins = frame_positive - frame_negative
                frame_index = int(margins.argmax().item())
                record[role] = (float(frame_positive[frame_index].item()),
                                float(frame_negative[frame_index].item()))
                cursor += p + n
            scores.append(record)
    return choose_verified_roles(scores)
