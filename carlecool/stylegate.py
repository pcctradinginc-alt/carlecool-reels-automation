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
    # brand products / ad looks (Reel #39: Coca-Cola). Champagne is back (owner's guide,
    # 27 Nov: Old-Hollywood glamour) — brand logos stay out.
    "coca cola", "coca-cola", "coke", "pepsi", "starbucks", "mcdonald", "red bull",
    # work / everyday scenes outside the brief (Reel #39: construction workers, video call)
    "construction", "workers", "welding", "welder", "factory", "video call", "video calling", "zoom call", "warehouse",
    # studio fashion shoots (Reel #41 opened on "Chic Studio Fashion Portrait with Unique Backdrop")
    "fashion portrait", "fashion shoot", "photo shoot", "photoshoot", "studio portrait", "backdrop",
    "model posing", "lookbook", "catwalk", "runway",
    # owner 23 Nov (Reel #43): no Dutch houses, no flower / butterfly close-ups
    "dutch", "netherlands", "holland", "amsterdam", "windmill", "tulip", "canal house",
    "flower", "flowers", "blossom", "butterfly", "butterflies", "bouquet",
    # owner 23 Nov: no pride / rainbow flags anywhere (the flag motif is the US flag only).
    # Only the flag object — never a reason to drop a clip because of who is in it.
    "pride flag", "rainbow flag", "pride parade", "lgbt flag", "lgbtq flag",
    # selfie / phone-filming looks (Reel #44: "Taking selfies at night")
    "selfie", "selfies",
    # Reel #46: modern water toys instead of classic sailing; snow / winter dates a Reel
    "speedboat", "speed boat", "motorboat", "motor boat", "jet ski", "jetski", "jet-ski",
    "jetskiing", "wakeboard", "powerboat", "cruising boat", "cruising in the ocean", "yacht",
    "snow", "snowy", "snowfall", "winter", "frozen", "skiing", "ski ", "snowboard",
    # Reel #47: surreal / fantasy staging ("Whimsical Picnic in Pastel Paradise",
    # "Magical Picnic with Floating Tennis Balls") is not timeless-classic
    "whimsical", "magical", "floating", "fantasy", "surreal", "dreamlike", "pastel paradise",
    # Reel #48: modern car brands, London instead of America, chores / tired drivers
    "bmw", "mercedes", "audi", "volkswagen", "toyota", "honda", "hyundai", "kia",
    "london", "piccadilly", "big ben", "picking up trash", "trash", "garbage", "litter",
    "yawning", "tired driver",
    # Reel #54: modern landmark architecture is not timeless-classic
    "the vessel", "vessel new york", "hudson yards", "modern architecture", "glass facade", "glass building",
    "skyscraper construction", "futuristic", "oculus",
    # owner 27 Nov (Reel #62): no romantic couples; people on screen are women only.
    # Whole words (titles are padded), so "man" never matches "woman".
    "couple", "couples", "kissing", "kiss", "kisses", "romantic", "romance", "lovers", "in love",
    "honeymoon", "wedding", "bride", "groom", "boyfriend", "husband",
    "man", "men", "guy", "guys", "boy", "boys", "gentleman", "father", "dad", "grandfather",
    "businessman", "his",
    # Reel #62: nudity (AI clip) — never
    "nude", "naked", "topless",
    # bibles (27 Nov): no smoking (Reel #92: "Brunette woman smoking outside in the rain")
    "smoking", "smoke a cigarette", "cigarette", "cigarettes", "vaping", "vape",
    # Reel #87: minors and pandemic / medical looks are off-brief (women only, timeless)
    "teen", "teens", "teenager", "teenagers", "kid", "kids", "child", "children",
    "doctor", "nurse", "face mask", "wearing mask", "mask",
    # Reel #67 (owner: "die Frau auf dem Balkon passt nicht"): posed influencer / ad-copy
    # portraits ("Elegant Nightscape: A Woman on a Balcony", "Posing on the street",
    # "Stylish Night Portrait") and off-brief objects ("Set of bits in a toolbox")
    "balcony", "posing", "poses", "stylish", "elegant", "toolbox", "tools", "drill bits",
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
    "a person taking a selfie or filming with a smartphone",  # timeless, not trendy social-media content
    # owner 23 Nov (Reel #43)
    "a dutch brick house with gabled roofs or a canal", "a close-up of flowers or butterflies in a field",
    "a rainbow pride flag",  # the flag object only (owner 23 Nov)
    "a modern motorboat, speedboat or jet ski on the water",  # Reel #46
    "a snowy winter landscape",  # Reel #46 (seasonal, dates the Reel)
    # owner 27 Nov (Reel #62): women only, no romantic couples, never nudity
    "a romantic couple kissing or embracing", "a man as the main subject of the picture",
    "a naked or nude person",
)
WANTED = {
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
              "a black and white portrait of a woman musician", "a 1990s hip hop studio with turntables and a sampler",
              "a bare wooden staircase in a white room", "a woman walking on a beach in black and white",
              "a long wooden table in an empty white room",
              # owner's night references (night variant of either world)
              "a neon-lit american diner at blue hour", "a lonely late-night diner seen through a window",
              "palm trees against a deep blue evening sky", "car light trails on a city freeway at night",
              "an elevated train viaduct lit at night", "brownstones and lit apartment windows at night",
              "an american flag at night with city lights", "a starry sky over a beach fence",
             # "Drive" (2011) stills
             "the inside of a car driving at night with city lights outside",
             "a driver's eyes in a rearview mirror at night", "an empty road under sodium street lights",
             "a night city skyline seen from an apartment window", "a dim garage with a classic car",
             "a woman in a warm-lit hallway at night"),
}
# Creative Directors (27 Nov): each director brings the image prompts it looks for.
from . import directors as _directors  # noqa: E402
for _n, _d in _directors.load_all().items():
    WANTED[_n] = tuple(_d.get("wanted") or ())
    if _d.get("variant") is None:
        WANTED.setdefault(_d["world"], WANTED[_n])
MARGIN = 0.0


def _norm(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", (text or "").lower()) + " "


# The flag slot is about the faded US flag of the Americana brief: other flags (pride /
# rainbow, national flags of other countries) are a different motif, so they are kept out
# of the FLAG slot and the "american flag" search lane — people in a clip are never judged.
OTHER_FLAGS = ("pride flag", "rainbow flag", "rainbow", "pride", "lgbt flag", "canadian flag",
               "uk flag", "union jack", "mexican flag", "eu flag", "german flag")
US_FLAG_WORDS = ("us", "usa", "u s", "american", "america", "united states", "stars and stripes",
                 "old glory", "star spangled")


def flag_mismatch(video) -> str | None:
    """Only the TITLE, and only when it is about a flag: tags such as "pride" on a clip of a
    couple must never exclude people (run 45057960429 dropped "A gay couple holding hands")."""
    title = _norm(getattr(video, "title", "") or "")
    if " flag " not in title and " flags " not in title:
        return None
    word = next((w for w in OTHER_FLAGS if _norm(w) in title), None)
    if word:
        return word
    # Owner: US flag only. A flag title without a US word is another country's flag
    # (Reel #44: "Philippines flag").
    if not any(_norm(w) in title for w in US_FLAG_WORDS):
        return "not a US flag"
    return None


# Coverr tags are broad ("santa monica", "jungle", "laptop", "valentine" on harmless clips),
# so tags only block clearly synthetic looks; everything else is judged on the title.
TAG_BLOCK = ("anthropomorphic", "animated", "animation", "cartoon", "3d", "cgi", "render", "rendered",
             "ai generated", "ai-generated", "illustration", "motion graphic", "claymation", "anime")


_BLOCKED_CLIPS: dict[str, str] | None = None


def blocked_clips() -> dict[str, str]:
    """Clips the owner rejected by name (data/blocked-clips.json)."""
    global _BLOCKED_CLIPS
    if _BLOCKED_CLIPS is None:
        try:
            import json
            path = Path(__file__).resolve().parent.parent / "data" / "blocked-clips.json"
            _BLOCKED_CLIPS = dict(json.loads(path.read_text(encoding="utf-8")).get("clips") or {})
        except (OSError, ValueError):
            _BLOCKED_CLIPS = {}
    return _BLOCKED_CLIPS


# Owner, 28 Nov: "Skater dürfen männlich und weiblich sein, bei allen anderen nur Frauen".
MALE_WORDS = ("man", "men", "guy", "guys", "boy", "boys", "gentleman", "his", "father", "dad",
              "grandfather", "businessman", "husband", "boyfriend")
MALE_PROMPTS = ("a man as the main subject of the picture",)
SKATE_WORDS = ("skate", "skater", "skaters", "skateboard", "skateboarder", "skateboarding", "skatepark")


def is_skate(title: str) -> bool:
    t = _norm(title)
    return any(f" {w} " in t for w in SKATE_WORDS)


def blocked_words(video) -> str | None:
    """The first block word in the title (any list) or in the tags (synthetic looks only).
    Skaters may be men or women; for every other picture the people rules stay."""
    if str(getattr(video, "id", "") or "") in blocked_clips():
        return "rejected by the owner"
    raw = getattr(video, "title", "") or ""
    title = _norm(raw)
    skate = is_skate(raw)
    for word in BLOCK_WORDS:
        if skate and word in MALE_WORDS:
            continue
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
        wanted = WANTED.get(_directors.key(world) or "") or WANTED.get(world or "", WANTED["lana"])
        # Phase 2: era / clothing / vehicle negatives of the director (e.g. modern smartphones)
        unwanted = list(UNWANTED) + list((_directors.get(_directors.key(world)) or {}).get("unwanted") or [])
        prompts = [f"a photo of {p}" for p in wanted] + unwanted
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
                out.append((max(good) - bad[worst], unwanted[worst]))
        return out
    except Exception as exc:
        print("Style gate unavailable:", type(exc).__name__)
        return [None] * len(images)


def rejected(verdict: tuple[float, str] | None) -> bool:
    return verdict is not None and verdict[0] < MARGIN


# ---------------------------------------------------------------- owner reference images
REF_DIR = Path(__file__).resolve().parent.parent / "data" / "style-refs"
REF_WEIGHT = 5.0  # 27 Nov (Reel #62: "passen kaum zu den Beispielbildern"): was 3.0. Ranking bonus per unit of similarity above the candidates' median (owner: closer to the examples)


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


NEIGHBORS_K = 3  # mean of the 3 closest reference images (24 Nov calibration)
# Below this a stock clip is too far from the owner's references (63 Coverr thumbnails:
# lower quartile ≈0.25 — modern supercars, construction, MPC close-ups, Mexico street).
REF_FLOOR = 0.25
CAR_WORDS = ("porsche", "land rover", "range rover", "defender", "classic car", "convertible", "car")


def is_car_query(query: str | None) -> bool:
    q = " " + (query or "").lower() + " "
    return any(" " + w + " " in q for w in CAR_WORDS)


def load_neighbors(name: str | None):
    """One vector per reference image (float16, base64) as a torch tensor, or None."""
    import base64
    import json
    try:
        import numpy as np
        import torch
        doc = json.loads((REF_DIR / f"{name}.json").read_text(encoding="utf-8"))
        nb = doc.get("neighbors") or {}
        if nb.get("dtype") != "float16":
            return None
        arr = np.frombuffer(base64.b64decode(nb["data"]), dtype=np.float16).reshape(nb["shape"])
        return torch.nn.functional.normalize(torch.tensor(arr.astype("float32")), dim=-1)
    except Exception:
        return None


def neighbor_score(vec, neighbors, k: int = NEIGHBORS_K) -> float:
    """Mean similarity to the k closest reference images.

    Calibrated on the owner's images vs 63 real Coverr thumbnails (24 Nov): a single mean
    vector let Christmas clips score like vinyl; nearest neighbours keep the several looks
    of a world apart (porch, flag, sailing, people …). Lana: 72 % instead of 63 % of the
    references score above the best off-brief stock clip; Night: 97 % instead of 89 %.
    """
    sims = neighbors @ vec
    return float(sims.topk(min(k, len(sims))).values.mean())


def reference_similarity(images, world: str | None, clip) -> list[float | None]:
    """Cosine similarity of each thumbnail to the owner's references (None = unscored).

    Used for RANKING only (closer to the owner's examples = earlier), never as a hard gate:
    the references show the look (era, light, colour, setting), the gate keeps out content.
    """
    ref = load_reference(world)
    neighbors = load_neighbors(world)
    if (ref is None and neighbors is None) or clip is None or not images:
        return [None] * len(images)
    try:
        import torch
        from PIL import Image
        model, preprocess, _tok = clip
        ref_t = (torch.nn.functional.normalize(torch.tensor(ref, dtype=torch.float32), dim=-1)
                 if ref is not None else None)
        out = []
        with torch.no_grad():
            for image in images:
                if image is None:
                    out.append(None)
                    continue
                with Image.open(image) as img:
                    v = torch.nn.functional.normalize(
                        model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)[0]
                out.append(neighbor_score(v, neighbors) if neighbors is not None else float(v @ ref_t))
        return out
    except Exception as exc:
        print("Reference similarity unavailable:", type(exc).__name__)
        return [None] * len(images)


# ---------------------------------------------------------------- night: no daylight
# Reel #55 (Night · city at night) got a backyard, a sunset, clouds and a sunny terrace.
# Calibrated 26 Nov on the owner's 37 night references (mean luma: median 0.24, 90 % below
# 0.36) vs day images (median ≈0.57): a clip is "daylight" when its thumbnail is bright
# overall AND in its middle tones — blue hour, neon and lit streets stay in.
NIGHT_MAX_MEAN = 0.42
NIGHT_MAX_MEDIAN = 0.35


def too_bright_for_night(image) -> float | None:
    """Mean luma (0..1) when the picture looks like daylight, else None (or unreadable)."""
    try:
        import numpy as np
        from PIL import Image
        with Image.open(image) as img:
            px = np.asarray(img.convert("L").resize((96, 96)), dtype=float) / 255.0
    except Exception:
        return None
    mean, median = float(px.mean()), float(np.median(px))
    return round(mean, 3) if mean > NIGHT_MAX_MEAN and median > NIGHT_MAX_MEDIAN else None


# Owner, 28 Nov ("es muss besser werden"): Reel #92 showed basketball hoops for "baseball",
# a river and paragliding for "land rover". A clip must SHOW its search motif: the CLIP
# similarity to "a photo of <query>" must beat the best of a set of generic scenes /
# typical confusions. Signature roles keep their own gates.
GENERIC_SCENES = ("a landscape", "a river, lake or the sea", "a city street", "the sky and clouds",
                  "a person", "a room interior", "a basketball court", "people doing sports",
                  "a forest", "a beach", "a road", "a building")
RELEVANCE_MARGIN = 0.0


def relevance(images, queries: list[str], clip) -> list[float | None]:
    """Per image: sim(query) − max sim(generic scenes); None if unscored."""
    if clip is None or not images:
        return [None] * len(images)
    try:
        import torch
        from PIL import Image
        model, preprocess, tokenizer = clip
        uniq = sorted({q for q in queries if q})
        prompts = [f"a photo of {q}" for q in uniq] + [f"a photo of {g}" for g in GENERIC_SCENES]
        gen_words = [set(g.replace(",", " ").split()) for g in GENERIC_SCENES]
        with torch.no_grad():
            text = torch.nn.functional.normalize(model.encode_text(tokenizer(prompts)), dim=-1)
            out = []
            for image, q in zip(images, queries):
                if image is None or not q:
                    out.append(None)
                    continue
                with Image.open(image) as img:
                    v = torch.nn.functional.normalize(
                        model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)
                sims = (v @ text.T)[0].tolist()
                own = sims[uniq.index(q)]
                # a generic scene that names the motif itself (basketball → "a basketball court")
                # is not a confusion: owner, 28 Nov — basketball / streetball belong to Night
                words = set(q.split())
                sport = bool(words & {"basketball", "streetball", "tennis", "baseball", "polo", "skate",
                                      "skateboard", "skatepark", "surfer", "sailing", "regatta"})
                others = [s for s, g, gw in zip(sims[len(uniq):], GENERIC_SCENES, gen_words)
                          if not (words & gw - {"a", "or", "the"}) and not (sport and "sports" in g)]
                generic = max(others) if others else 0.0
                out.append(round(own - generic, 4))
        return out
    except Exception as exc:
        print("Relevance check unavailable:", type(exc).__name__)
        return [None] * len(images)
