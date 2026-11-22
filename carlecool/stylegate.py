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

from pathlib import Path
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
    # gear: analog only — no kitchen mixers, no laptop/controller DJ setups
    "kitchen", "blender", "laptop", "dj controller", "ipad",
    # holidays / seasons that date a Reel (Reel #39: two Christmas clips)
    "christmas", "xmas", "santa", "christmas tree", "gift bags", "new year", "halloween",
    "easter", "valentine",
    # brand products / ad looks (Reel #39: Coca-Cola, champagne)
    "coca cola", "coca-cola", "coke", "pepsi", "champagne", "starbucks", "mcdonald", "red bull",
    # work / everyday scenes outside the brief (Reel #39: construction workers, video call)
    "construction", "workers", "video call", "video calling", "zoom call", "warehouse",
    # studio fashion shoots (Reel #41 opened on "Chic Studio Fashion Portrait with Unique Backdrop")
    "fashion portrait", "fashion shoot", "photo shoot", "photoshoot", "studio portrait", "backdrop",
    "model posing", "lookbook", "catwalk", "runway",
)
UNWANTED = (
    "a cartoon or an animated film", "a 3d computer rendering", "an ai generated cartoon character",
    "a car with a cartoon face", "a sign with large written words", "a modern sports car or supercar",
    "a tropical volcano or jungle", "a busy street in latin america", "an office or a business meeting",
    "a product advertisement", "a screen with text or a user interface",
    "a modern porsche 911 from the 2020s with wide wheels",
    "a kitchen appliance", "a laptop computer with software on the screen",
    "christmas decorations, a christmas tree or gift bags", "a bottle or can of a soft drink brand",
    "construction workers at a building site", "a person on a video call",
    "a fashion model posing in a photo studio in front of a colored backdrop",
)
WANTED = {
    "lana": ("young friends together outdoors at golden hour", "a neon motel or diner sign at dusk",
             "an american flag waving", "a classic air-cooled porsche 911 from the 1990s",
             "a classic land rover defender",
             "a road trip on an empty american highway", "palm trees and a pale summer sky",
             "a skateboarder on a street", "a woman in natural light", "a vintage color home movie",
             "a city street at night with lights", "a sunset over a calm landscape",
             "a dj turntable with a vinyl record", "a vintage dj mixer or drum machine",
             # owner's references: 1960s New England sailing, Kodachrome summer, Hollywood glamour
             "a couple on a sailboat on a sunny day", "white sails against a blue sky and the sea",
             "a 1960s kodachrome color photo of people on a boat", "a woman with sunglasses and a headscarf",
             "a convertible car in california sunshine", "a swimming pool with palm trees",
             "a black and white documentary photo of two people",
             "a woman on a swing in golden backlight by a white picket fence",
             "an american flag against a pale teal sky", "a black and white street photo from the 1970s",
             "a classic black sedan parked on a street", "a backstage mirror with bulbs at night",
             # third set: Hamptons / Cape Cod summer, preppy East-Coast style
             "an american flag on a pole above sand dunes and a beach fence",
             "a weathered shingled beach house by the ocean", "a white colonial house with a flag and a lawn",
             "blue beach umbrellas under a clear blue sky", "a preppy outfit with a sweater over the shoulders",
             "a 1950s college group photo in black and white"),
    "rubin": ("young friends sitting together in silence", "an empty parking lot at dusk",
              "an american flag on a fence", "a classic land rover defender",
              "a classic air-cooled porsche 911 from the 1990s", "a neon diner or motel sign at night",
              "an american diner interior", "palm trees against a pale sky",
              "a basketball court in evening light", "a quiet street in a european city",
              "a skateboarder seen from behind", "a woman by a window in natural light",
              "a vintage color home movie", "an empty road under an overcast sky", "a calm landscape",
              "a turntable or analog synthesizer in a wooden studio", "a vintage drum machine or sampler",
              # owner's references: Rubin's house and studios, 90s hip-hop studios
              "a minimal white room with sunlight stripes through a window",
              "a large analog mixing console in a recording studio", "studio monitor speakers on a wooden wall",
              "a vintage organ or piano by a window with palm trees", "an acoustic guitar in a bright living room",
              "a black and white portrait of a bearded musician", "a 1990s hip hop studio with turntables and a sampler",
              "a bare wooden staircase in a white room", "a man walking on a beach in black and white",
              "a long wooden table in an empty white room"),
}
MARGIN = 0.0


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (text or "").lower()) + " "


# The flag slot is about the faded US flag of the Americana brief: other flags (pride /
# rainbow, national flags of other countries) are a different motif, so they are kept out
# of the FLAG slot and the "american flag" search lane — people in a clip are never judged.
OTHER_FLAGS = ("pride flag", "rainbow flag", "rainbow", "pride", "lgbt flag", "canadian flag",
               "uk flag", "union jack", "mexican flag", "eu flag", "german flag")


def flag_mismatch(video) -> str | None:
    """Only the TITLE, and only when it is about a flag: tags such as "pride" on a clip of a
    couple must never exclude people (run 45057960429 dropped "A gay couple holding hands")."""
    title = _norm(getattr(video, "title", "") or "")
    if " flag " not in title and " flags " not in title:
        return None
    return next((w for w in OTHER_FLAGS if _norm(w) in title), None)


# Coverr tags are broad ("santa monica", "jungle", "laptop", "valentine" on harmless clips),
# so tags only block clearly synthetic looks; everything else is judged on the title.
TAG_BLOCK = ("anthropomorphic", "animated", "animation", "cartoon", "3d", "cgi", "render", "rendered",
             "ai generated", "ai-generated", "illustration", "motion graphic", "claymation", "anime")


def blocked_words(video) -> str | None:
    """The first block word in the title (any list) or in the tags (synthetic looks only)."""
    title = _norm(getattr(video, "title", "") or "")
    for word in BLOCK_WORDS:
        if _norm(word) in title:
            return word
    tags = _norm(" ".join(getattr(video, "tags", ()) or ()))
    return next((w for w in TAG_BLOCK if _norm(w) in tags), None)


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


# ---------------------------------------------------------------- owner reference images
REF_DIR = Path(__file__).resolve().parent.parent / "data" / "style-refs"
REF_WEIGHT = 3.0  # ranking bonus per unit of similarity above the candidates' median (owner: closer to the examples)


def load_reference(world: str | None):
    """Mean OpenCLIP embedding of the owner's reference images for a world (or None)."""
    import json
    try:
        doc = json.loads((REF_DIR / f"{world}.json").read_text(encoding="utf-8"))
        vec = doc.get("embedding") or next(iter((doc.get("profiles") or {}).values()), None)
        return vec if isinstance(vec, list) and len(vec) >= 64 else None
    except (OSError, ValueError, TypeError):
        return None


def load_references(name: str | None) -> list[list[float]]:
    """All reference vectors of a profile: several sub-profiles (e.g. car: Land/Range Rover
    and Porsche 993) or the single mean embedding."""
    import json
    try:
        doc = json.loads((REF_DIR / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    vecs = list((doc.get("profiles") or {}).values()) or ([doc["embedding"]] if doc.get("embedding") else [])
    return [v for v in vecs if isinstance(v, list) and len(v) >= 64]


def reference_similarity(images, world: str | None, clip) -> list[float | None]:
    """Cosine similarity of each thumbnail to the owner's references (None = unscored).

    Used for RANKING only (closer to the owner's examples = earlier), never as a hard gate:
    the references show the look (era, light, colour, setting), the gate keeps out content.
    """
    ref = load_reference(world)
    if ref is None or clip is None or not images:
        return [None] * len(images)
    try:
        import torch
        from PIL import Image
        model, preprocess, _tok = clip
        ref_t = torch.nn.functional.normalize(torch.tensor(ref, dtype=torch.float32), dim=-1)
        out = []
        with torch.no_grad():
            for image in images:
                if image is None:
                    out.append(None)
                    continue
                with Image.open(image) as img:
                    v = torch.nn.functional.normalize(
                        model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)[0]
                out.append(float(v @ ref_t))
        return out
    except Exception as exc:
        print("Reference similarity unavailable:", type(exc).__name__)
        return [None] * len(images)
