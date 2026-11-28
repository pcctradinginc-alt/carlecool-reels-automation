"""Signature shots ADDED on top of the v4 footage: friends / couples, a skater, a woman,
an Americana detail and the cover motif.

Unlike the reverted Creative v5 (which replaced the v4 lanes with these subjects),
the proven v4 clips stay untouched; each signature clip is one extra interior shot.

* skater: face not visible — queries favour feet/wheels/silhouettes/back views, CLIP
  ranks "seen from behind" over "close-up face", and OpenCV rejects clips with a large
  frontal face.
* woman: candid, natural — CLIP prefers "candid, natural light" over "posed fashion
  model / heavy make-up".
* friends: small groups of young friends (18–25) together in real places; CLIP prefers
  candid laughter / walking / sitting together over ads, posing and crowds.
* americana: sparse symbolic detail (faded flag, motel/diner neon, old car, gas station);
  Lana leans on the dreamy roadside motifs, Rubin on quiet everyday ones.
* variety: clips used in the last 30 previews are never reused for these slots.
Every failure (quota, no hits, no model) just leaves the slot empty.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess

import numpy as np

from .video import Video, _coverr_request, _is_portrait

MEMORY_REELS = 30
# Owner: more room for friends and Americana; always a US flag; cars = classic Porsche
# (911 / 993 era) rather than generic cars.
SLOT_POSITION = {"friends": 0.25, "motif": 0.15, "flag": 0.38, "gear": 0.44, "skater": 0.5, "car": 0.62,
                 "woman": 0.72, "americana": 0.82, "friends2": 0.9}
PRIORITY = ("skater", "friends", "flag", "gear", "woman", "car", "americana", "friends2", "motif")
DEFAULT_PRIORITY = PRIORITY  # performance.role_priority() reorders a copy per Reel
MAX_ROLES = 8  # searched/downloaded roles per Reel (placement cap is ~40 % of the shots)
STRICT_ROLES = ("gear", "car", "flag")
REF_WEIGHT = 0.5  # reference similarity vs prompt score (owner: "people like in the example images")  # role negatives are specific → negative score = reject

SKATER_QUERIES = {
    "rubin": ("skateboard feet", "skateboard wheels", "skatepark"),
    None: ("skateboard feet", "skater silhouette", "skateboarding"),
}
FRIENDS_QUERIES = {  # owner 27 Nov (Reel #62): women only, no romantic couples
    "rubin": ("women walking", "women talking", "women sitting", "women beach"),
    None: ("women walking", "women together"),
}
AMERICANA_QUERIES = {
    "rubin": ("basketball court", "diner", "empty road", "gas station", "parking lot"),
    None: ("motel", "diner", "neon sign"),
}
FLAG_QUERIES = {
    "rubin": ("american flag", "usa flag", "flag"),
    None: ("american flag", "usa flag", "flag"),
}
# Owner: analog music gear in both worlds (Vestax mixer, Technics 1210 turntables, MPC 2000 …)
# — Lana: warm, vinyl at golden hour / neon; Rubin: wooden studio, hands, stillness.
GEAR_QUERIES = {
    "rubin": ("mixing console", "turntable", "recording studio", "piano", "synthesizer", "vinyl",
              "studio monitors", "drum machine"),
    None: ("turntable", "vinyl record", "dj mixer"),
}
CAR_QUERIES = {  # owner: Land Rover Defender, Range Rover (classic + modern), classic Porsche 993
    "rubin": ("land rover", "range rover", "porsche", "defender", "classic porsche", "classic car"),
    None: ("land rover", "range rover", "porsche", "classic car"),
}


def car_order(queries, run_key: str) -> list[str]:
    """Rotate Land Rover / Range Rover / Porsche to the front between Reels; rest keep order."""
    q = list(queries)
    if len(q) >= 3:
        k = hashlib.sha256(f"{run_key}|car".encode()).digest()[0] % 3
        q = q[k:3] + q[:k] + q[3:]
    return q
WOMAN_QUERIES = {
    "rubin": ("woman beach morning", "woman walking nature", "woman window"),
    None: ("woman walking sunset", "woman nature", "woman walking"),
}


# Creative Directors (27 Nov): role queries of Lana / Night live in directors/*.json.
from . import directors as _directors  # noqa: E402
_ROLE_TABLES = {"skater": SKATER_QUERIES, "woman": WOMAN_QUERIES, "friends": FRIENDS_QUERIES,
                "americana": AMERICANA_QUERIES, "flag": FLAG_QUERIES, "car": CAR_QUERIES, "gear": GEAR_QUERIES}
for _n, _d in _directors.load_all().items():
    for _role, _table in _ROLE_TABLES.items():
        if (_d.get("roles") or {}).get(_role):
            _table[_n] = tuple(_d["roles"][_role])


def queries_for(role: str, style: str | None, variant: str | None = None, theme: str | None = None) -> tuple[str, ...]:
    """Search words of a signature role; a theme may bring its own (owner, 28 Nov: the woman
    shot of an Analog-Music Reel must not be searched as "woman horse")."""
    if theme:
        from . import themes as _themes
        info = _themes.get(style, variant, theme) or {}
        own = (info.get("role_queries") or {}).get(role if role != "friends2" else "friends")
        if own:
            return tuple(own)
    table = {"skater": SKATER_QUERIES, "woman": WOMAN_QUERIES, "friends": FRIENDS_QUERIES,
             "friends2": FRIENDS_QUERIES, "americana": AMERICANA_QUERIES, "flag": FLAG_QUERIES,
             "car": CAR_QUERIES, "gear": GEAR_QUERIES}[role]
    key = _directors.key(style, variant)
    return tuple(table.get(key, table.get(style, table[None])))
PROMPTS = {
    "skater": (
        ("a skateboarder seen from behind, face not visible",
         "close-up of feet on a skateboard rolling on asphalt",
         "silhouette of a skater against the sky"),
        ("a close-up portrait of a person's face",
         "a skateboard lying on the ground without a person",
         "an empty street without people"),
    ),
    "woman": (
        ("a candid natural photo of a woman outdoors in natural light",
         "a woman walking, documentary style, no posing",
         "a woman in a waxed field jacket and rubber boots in the countryside",
         "a woman at a muddy music festival in wellington boots",
         "a woman in a white t-shirt and denim with gold hoop earrings and long wavy hair",
         "a black and white portrait of a woman with long dark wavy hair",
         "a woman with hair blowing in the wind"),
        ("a glamorous posed fashion model in a studio",
         "a heavy make-up beauty close-up",
         "a man", "an empty landscape without people"),
    ),
    "friends": (
        ("a small group of young women laughing together outdoors, candid",
         "young women walking side by side on a city street",
         "women friends sitting close together on a curb or rooftop at sunset",
         "two young women together, natural documentary photo"),
        ("an advertisement with models posing for the camera", "a man", "a romantic couple",
         "a crowd at a concert or a party", "a business meeting in an office",
         "a single person alone", "an empty street without people"),
    ),
    "americana": (
        ("a faded american flag moving in the wind",
         "a neon motel or diner sign at dusk", "an old american car parked on a roadside",
         "an old gas station or an empty highway at sunset"),
        ("a brand logo or an advertisement", "a political rally or a parade with crowds",
         "soldiers or military", "text or a document"),
    ),
    "flag": (
        ("an american flag waving in the wind", "a faded us flag on a porch or a pole",
         "an american flag against the sky at sunset"),
        ("a political rally or a protest", "soldiers or military", "a crowd at a parade",
         "a flag of another country", "a rainbow flag", "text or a document"),
    ),
    "car": (
        ("a classic porsche 911 sports car", "a classic land rover defender off-road vehicle",
         "a range rover on a country road", "a land rover in the british countryside",
         "a restored classic porsche 911 with round headlights on a mountain road",
         "a vintage sports car on an open road",
         "a classic car driving at sunset"),
        ("a minivan or a small city car", "a car crash or an accident", "a car dealership or showroom",
         "a traffic jam", "a race track with crowds"),
    ),
    "gear": (
        ("a dj turntable with a spinning vinyl record", "hands on a dj mixer with faders and knobs",
         # unified bible (27 Nov): analog music in every Reel
         "fingers pressing the rubber pads of an mpc sampler", "an analog synthesizer with knobs and patch cables",
         "a vintage drum machine with colored step buttons", "hands playing a rhodes electric piano",
         "a reel-to-reel tape recorder with spinning reels", "a cassette tape in a tape deck",
         "a silver 1990s boombox", "glowing vu meters on an analog mixing console",
         "a vintage drum machine or sampler with rubber pads", "an analog synthesizer with knobs",
         "a large analog mixing console with many faders", "a piano or organ by a bright window",
         "a record player needle on vinyl in warm light"),
        ("a laptop with dj software on the screen", "a kitchen mixer or blender",
         "a crowded nightclub with stage lights", "a mixing console in a large concert hall",
         "a toy or a cartoon",
         # owner, 28 Nov: instrument close-ups — not record shops, sleeves or crates
         "hands flipping through record sleeves in a record store", "crates of vinyl records in a shop",
         "a wide shot of a room"),
    ),
    "motif": None,
}
PROMPTS["friends2"] = PROMPTS["friends"]
FACE_MAX_HEIGHT = 0.12  # frontal face taller than 12 % of the frame → skater rejected


def enabled() -> bool:
    return os.getenv("CARLECOOL_SIGNATURE", "true").strip().lower() in ("true", "1", "yes", "on")


def _rotate(queries: tuple[str, ...], key: str) -> list[str]:
    start = int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") % len(queries)
    return list(queries[start:]) + list(queries[:start])


def item_view(item: dict):
    """Minimal title/tags view of a raw Coverr item for the word gate."""
    from types import SimpleNamespace
    return SimpleNamespace(title=str(item.get("title") or ""),
                           tags=tuple(str(t) for t in (item.get("tags") or []) if isinstance(t, str)))


def search_slot(api_key: str, queries, *, exclude: set[str], session=None,
                per_query: int = 30, enough: int = 4, role: str = "") -> list[Video]:
    """Up to 3 Coverr requests; stops once `enough` usable clips were found."""
    import requests
    session = session or requests.Session()
    found: list[Video] = []
    for query in list(queries)[:3]:
        if len(found) >= enough:
            break
        try:
            hits = _coverr_request(session, api_key, query, per_query)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            from .video import coverr_blocked, describe_error
            print(f"Signature {role} '{query}' failed: {describe_error(exc)}")
            if coverr_blocked():
                break
            continue
        for item in hits:
            vid = str(item.get("id", ""))
            urls = item.get("urls") or {}
            url = urls.get("mp4_download") or urls.get("mp4")
            if (not vid or vid in exclude or not url
                    or any(item.get(f) is True for f in ("is_premium", "premium", "is_sponsored",
                                                         "sponsored", "is_watermarked"))):
                continue
            exclude.add(vid)
            from .stylegate import blocked_words
            word = blocked_words(item_view(item))
            if not word:  # US flag only, in every role
                from .stylegate import flag_mismatch
                word = flag_mismatch(item_view(item))
            if word:
                print(f"Signature {role} candidate rejected ('{word}'): {vid}")
                continue
            from .video import _coverr_creator_metadata, coverr_page
            name, link = _coverr_creator_metadata(item)
            found.append(Video(vid, "coverr", url=url, title=item.get("title", ""),
                               vertical=_is_portrait(item), creator_name=name, creator_url=link,
                               query=query, thumb_url=str(item.get("thumbnail") or item.get("poster") or ""),
                               tags=tuple(str(t).lower() for t in (item.get("tags") or []) if isinstance(t, str))[:30],
                               page_url=coverr_page(item)))
        print(f"Signature {role} '{query}': {len(hits)} hits")
    return found


def rank(role: str, candidates: list[Video], workdir: Path, world: str | None = None) -> list[Video]:
    """Order by CLIP (positive − negative prompt similarity) plus closeness to the owner's
    reference images of the style world (people, wardrobe, era, light); keyword fallback."""
    prompts = PROMPTS.get(role)
    keywords = {"skater": ("skate",), "woman": ("woman",), "friends": ("women", "friend"),
                "friends2": ("women", "friend"), "flag": ("flag",),
                "car": ("porsche", "land rover", "range rover", "defender"),
                "gear": ("turntable", "vinyl", "mixer", "record", "synth", "drum")}.get(role, ("",))
    fallback = sorted(candidates, key=lambda v: (not any(k in " ".join(v.tags + (v.title.lower(),))
                                                         for k in keywords), not v.vertical))
    if not prompts or not candidates:
        return fallback
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is None:
        return fallback
    from .curation import download_thumbnail
    try:
        import torch
        from PIL import Image
        model, preprocess, tokenizer = clip
        positive, negative = prompts
        from .stylegate import MALE_PROMPTS, UNWANTED, load_neighbors, load_references, neighbor_score
        # skaters may be men or women (owner, 28 Nov); every other role keeps the people rules
        UNWANTED = tuple(u for u in UNWANTED if not (role == "skater" and u in MALE_PROMPTS))
        # Cars: best match to any owner car profile (Land/Range Rover, Porsche 993);
        # other roles: the style world's references.
        people_roles = ("woman", "friends", "friends2", "skater")
        refs = ((load_references("car") if role == "car" else [])
                or ((load_references("people") + load_references(world)[:1]) if role in people_roles else [])
                or load_references(world)[:1])
        ref_t = (torch.nn.functional.normalize(torch.tensor(refs, dtype=torch.float32), dim=-1)
                 if refs else None)
        # Nearest owner reference images of the world (not for cars: own car profiles)
        world_nb = load_neighbors(world) if role != "car" else None
        with torch.no_grad():
            text = torch.nn.functional.normalize(
                model.encode_text(tokenizer(list(positive + negative + UNWANTED))), dim=-1)
            scored = []
            gated = 0
            for i, video in enumerate(candidates[:16]):
                thumb = download_thumbnail(video.thumb_url, workdir / f"sig_{role}_{i}.jpg")
                if thumb is None:
                    continue
                if world == "night":
                    from .stylegate import too_bright_for_night
                    luma = too_bright_for_night(thumb)
                    if luma is not None:  # Reel #55: sunny terrace / clouds in a Night Reel
                        print(f"Signature {role} candidate rejected (daylight, luma {luma}): {video.id}")
                        thumb.unlink(missing_ok=True)
                        gated += 1
                        continue
                with Image.open(thumb) as img:
                    v = torch.nn.functional.normalize(
                        model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0)), dim=-1)
                thumb.unlink(missing_ok=True)
                sims = (v @ text.T)[0].tolist()
                pos = max(sims[:len(positive)])
                unwanted = sims[len(positive) + len(negative):]
                if max(unwanted) > pos:  # cartoon, render, modern supercar … wins → drop
                    print(f"Signature {role} candidate rejected (style gate): {video.id}")
                    gated += 1
                    continue
                score = pos - max(sims[len(positive):len(positive) + len(negative)]) + (0.01 if video.vertical else 0)
                if role in STRICT_ROLES and score < 0:
                    # e.g. a laptop DJ setup for "gear", a modern SUV for "car": drop, don't rank last
                    print(f"Signature {role} candidate rejected (looks off-brief): {video.id}")
                    gated += 1
                    continue
                ref_parts = ([float((ref_t @ v[0]).max())] if ref_t is not None else []) + \
                    ([neighbor_score(v[0], world_nb)] if world_nb is not None else [])
                if ref_parts:  # look like the owner's example images (styling, era, light)
                    score += REF_WEIGHT * max(ref_parts)
                scored.append((score, i))
        if not scored:
            # Everything failed the style gate → better no clip than a wrong one; no
            # thumbnails at all → keyword order as before.
            return [] if gated else fallback
        order = [i for _, i in sorted(scored, key=lambda x: -x[0])]
        return [candidates[i] for i in order]
    except Exception as exc:
        print(f"Signature {role} ranking failed: {type(exc).__name__}")
        return fallback


def largest_face_ratio(path: Path, *, samples: int = 4, width: int = 480) -> float:
    """Height of the largest frontal face / frame height over a few frames (0 = none).

    Returns 0.0 when OpenCV is unavailable (check skipped).
    """
    try:
        import cv2
    except ImportError:
        return 0.0
    from .render import probe_dimensions
    src_w, src_h = probe_dimensions(path)
    if src_w <= 0 or src_h <= 0:
        return 0.0
    h = max(2, int(round(width * src_h / src_w / 2)) * 2)
    proc = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf",
                           f"fps=1,scale={width}:{h},format=gray", "-frames:v", str(samples),
                           "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          capture_output=True, timeout=60)
    count = len(proc.stdout) // (width * h)
    if count < 1:
        return 0.0
    frames = np.frombuffer(proc.stdout[:count * width * h], dtype=np.uint8).reshape(count, h, width)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    worst = 0.0
    for frame in frames:
        for (_x, _y, _w, fh) in cascade.detectMultiScale(frame, scaleFactor=1.1, minNeighbors=6,
                                                         minSize=(24, 24)):
            worst = max(worst, fh / h)
    return float(worst)


def place_signature_shots(shots, durations: list[float], slots: dict[str, int]):
    """Ensure each signature source appears in one interior shot near its position.

    `slots` maps role → source index. Shots 0 and last stay (cover-matched bookends).
    """
    from .cinematic import Shot
    shots = list(shots)
    if len(shots) < 3:
        return shots
    # v4 footage must stay present (lesson from Creative v5): at most about half of the
    # interior shots become signature shots; skater, friends and woman come first.
    limit = max(1, int(0.4 * (len(shots) - 2)) + 1)  # ~40 %: the edit must not become a collage
    chosen = sorted(slots.items(), key=lambda kv: PRIORITY.index(kv[0]) if kv[0] in PRIORITY else 9)[:limit]
    taken: set[int] = set()
    for role, source in sorted(chosen, key=lambda kv: SLOT_POSITION.get(kv[0], 0.5)):
        if any(s.source_index == source for s in shots[1:-1]):
            taken |= {i for i, s in enumerate(shots) if s.source_index == source}
            continue
        target = SLOT_POSITION.get(role, 0.5) * (len(shots) - 1)
        interior = [i for i in range(1, len(shots) - 1) if i not in taken]
        if not interior:
            break
        index = min(interior, key=lambda i: abs(i - target))
        length = shots[index].duration
        dur = durations[source]
        offset = max(0.0, (dur - length) / 2) if dur > length else 0.0
        shots[index] = Shot(source, round(offset, 3), length)
        taken.add(index)
    return shots
