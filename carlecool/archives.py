"""Free archival footage: NASA (space, Earth) and Prelinger Archives (vintage Americana).

* NASA Image & Video Library (images-api.nasa.gov, no key): generally not
  copyrighted; never use NASA logos or imply endorsement. Used for the Rubin
  (space/minimal) and Night (Earth at night) styles.
* Internet Archive home movies (archive.org, no key): curated collections only —
  Prelinger Archives, Prelinger home movies, Home Movies, California Revealed (Californian
  libraries and archives) and Orange County Archives — and ONLY items explicitly marked
  public domain (`licenseurl` …/publicdomain/); used for the Lana/Americana look.

Films are long (minutes to hours, up to GB), so only a short segment is cut
straight from the remote file via HTTP range requests (no full download).
The segment start is taken from the middle of the film (skips title cards and end
slates). Content safety: titles with disturbing topics are excluded, and with
OpenCLIP a frame of the segment must look more like the wanted scene than like an
accident, weapons, interview/talking head, text card or blank frame.
The owner still reviews every Reel before anything is published.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, urlparse

import requests

from .video import Video

NASA_SEARCH = "https://images-api.nasa.gov/search"
NASA_HOST = "images-assets.nasa.gov"
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_META = "https://archive.org/metadata/"
SEGMENT_SECONDS = 9.0
MAX_CLIPS = 2

NASA_QUERIES = {
    "rubin": ("earth from orbit", "earth views", "jupiter", "saturn", "moon", "nebula", "galaxy"),
    "night": ("earth at night", "black marble", "aurora", "earth views"),
}
PRELINGER_QUERIES = {
    # Amateur films only: real summers, roads and beaches; no ads, no propaganda.
    "lana": ("amateur film", "home movie", "home movies", "family", "beach", "summer",
             "vacation", "picnic", "parade", "road trip", "fair"),
}
# Curated archive.org collections (owner, 24 Nov: more free footage). Community uploads
# are left out: there the "public domain" mark is only the uploader's own claim.
ARCHIVE_COLLECTIONS = {"prelinger": "Prelinger Archives", "prelingerhomemovies": "Prelinger Archives",
                       "home_movies": "Internet Archive Home Movies",
                       "californiarevealed": "California Revealed",
                       "orangecountyarchives": "Orange County Archives"}
NASA_EXCLUDE = ("briefing", "conference", "interview", "news", "media", "talk", "lecture",
                "panel", "podcast", "this week", "live", "tour", "event", "award", "ceremony",
                "update", "explained", "q&a", "town hall", "webinar", "launch coverage", "hearing",
                "expert", "asked", "trailer", "countdown", "inside ksc", "candid", "mission video",
                "inspiration", "highlights", "expo", "air show", "defenders", "welcome", "how ",
                "why ", "what ", "science live", "ask nasa", "asknasa", "anniversary", "student")
PRELINGER_EXCLUDE = ("crash", "accident", "signal 30", "war", "atomic", "bomb", "murder",
                     "death", "dead", "safety", "drug", "venereal", "disease", "crime",
                     "delinquen", "prison", "hospital", "surgery", "military", "army", "navy",
                     "nazi", "communis", "propaganda", "alcohol", "drunk", "gun", "weapon",
                     "kill", "blood", "fire", "disaster", "riot", "race", "negro", "indian",
                     "chevrolet", "ford", "general motors", "motorama", "advertis", "commercial",
                     "sponsor", "coca", "pepsi", "initiation", "snowstorm", "world's fair",
                     "halloween", "christmas", "santa", "easter", "haunt", "ghoul", "church",
                     "baptist", "sunday school", "funeral", "storm", "flood", "armistice",
                     "germany", "v-e day", "veteran", "police", "lecture", "interview",
                     "oral history", "council", "meeting", "hearing", "disney", "knott")
THIRD_PARTY = ("esa", "european space agency", "jaxa", "csa", "dlr", "herschel", "planck", "gaia",
               "sofia", "courtesy of", "copyright", "©", "getty", "ap photo", "reuters")
POSITIVE = {
    "nasa": ("the earth or a planet seen from space",
             "stars, a nebula or a galaxy in deep space",
             "the surface of the moon or a planet"),
    "prelinger": ("a sunny vintage color home movie of a road trip",
                  "a vintage color home movie of a beach or summer day",
                  "an old color film of an american highway, car or small town"),
}
NEGATIVE = {
    "nasa": ("a spacecraft or rocket with a logo", "an astronaut or a person",
             "a scientist speaking to the camera", "an infographic, chart or text on screen",
             "a logo or graphic on a plain background", "a black or blank screen",
             "a control room or office"),
    "prelinger": ("a black and white film", "a title card with large text",
                  "a car brand logo or an advertisement", "people exercising in a gym",
                  "a car crash or an accident", "soldiers with weapons or war",
                  "a person talking to the camera in an interview", "a black or blank screen"),
}
MIN_MARGIN = 0.02


def enabled() -> bool:
    return os.getenv("CARLECOOL_ARCHIVES", "true").strip().lower() in ("true", "1", "yes", "on")


def _clean(text) -> str:
    if isinstance(text, list):
        text = " ".join(map(str, text))
    return str(text or "").lower()


def _blocked(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(w), text) for w in words)


def search_nasa(queries, exclude: set[str], *, session=None, rows: int = 12) -> list[dict]:
    session = session or requests.Session()
    items = []
    for query in queries:
        r = session.get(NASA_SEARCH, params={"q": query, "media_type": "video", "page_size": rows},
                        timeout=25)
        r.raise_for_status()
        for it in r.json().get("collection", {}).get("items", []):
            meta = (it.get("data") or [{}])[0]
            nasa_id = str(meta.get("nasa_id") or "")
            text = _clean(meta.get("title")) + " " + _clean(meta.get("keywords"))
            credits = _clean(meta.get("description")) + " " + _clean(meta.get("secondary_creator"))
            # NASA media can embed partner imagery (ESA, JAXA …) that is NOT public domain.
            if (not nasa_id or f"nasa-{nasa_id}" in exclude or _blocked(text, NASA_EXCLUDE)
                    or _blocked(credits + " " + text, THIRD_PARTY)):
                continue
            items.append({"id": f"nasa-{nasa_id}", "source": "nasa", "query": query,
                          "title": str(meta.get("title") or "")[:120], "nasa_id": nasa_id,
                          "manifest": str(it.get("href") or "")})
        if len(items) >= 8:
            break
    return items


def nasa_media_url(item: dict, *, session=None) -> str:
    """Prefer the original master, fall back to ~large; HTTPS on the NASA asset host only."""
    session = session or requests.Session()
    manifest = item["manifest"].replace("http://", "https://", 1)
    if urlparse(manifest).hostname != NASA_HOST:
        raise ValueError("Unexpected NASA manifest host")
    r = session.get(quote(manifest, safe=":/~@"), timeout=25)
    r.raise_for_status()
    urls = [u.replace("http://", "https://", 1) for u in r.json() if isinstance(u, str)]
    for suffix in ("~orig.mp4", "~large.mp4", "~medium.mp4"):
        match = next((u for u in urls if u.endswith(suffix)), None)
        if match and urlparse(match).hostname == NASA_HOST:
            return quote(match, safe=":/~@")
    raise ValueError("No usable NASA video rendition")


def search_prelinger(queries, exclude: set[str], *, session=None, rows: int = 150) -> list[dict]:
    session = session or requests.Session()
    terms = " OR ".join(f'title:"{q}"' for q in queries)
    cols = " OR ".join(f"collection:{c}" for c in ARCHIVE_COLLECTIONS)
    r = session.get(IA_SEARCH, timeout=25, params={
        "q": f"({cols}) AND mediatype:movies AND licenseurl:*publicdomain* AND ({terms})",
        "fl[]": ["identifier", "title", "licenseurl", "subject", "collection"], "rows": rows,
        "output": "json", "sort[]": "downloads desc"})
    r.raise_for_status()
    items = []
    for doc in r.json().get("response", {}).get("docs", []):
        ident = str(doc.get("identifier") or "")
        text = _clean(doc.get("title")) + " " + _clean(doc.get("subject"))
        if (not re.fullmatch(r"[A-Za-z0-9._-]{3,120}", ident) or f"pl-{ident}" in exclude
                or "publicdomain" not in _clean(doc.get("licenseurl")) or _blocked(text, PRELINGER_EXCLUDE)):
            continue
        cols = doc.get("collection") or []
        cols = cols if isinstance(cols, list) else [cols]
        archive = next((ARCHIVE_COLLECTIONS[c] for c in cols if c in ARCHIVE_COLLECTIONS), "Prelinger Archives")
        items.append({"id": f"pl-{ident}", "source": "prelinger", "identifier": ident, "archive": archive,
                      "title": str(doc.get("title") or "")[:120], "query": "vintage americana"})
    return items


def prelinger_media(item: dict, *, session=None) -> tuple[str, float]:
    session = session or requests.Session()
    r = session.get(IA_META + item["identifier"], timeout=25)
    r.raise_for_status()
    data = r.json()
    if "publicdomain" not in _clean((data.get("metadata") or {}).get("licenseurl")):
        raise ValueError("Item is not marked public domain")
    item["licence_url"] = str((data.get("metadata") or {}).get("licenseurl") or "")[:200]
    best = None
    for f in data.get("files", []):
        name = str(f.get("name") or "")
        if not name.lower().endswith(".mp4") or "/" in name:
            continue
        try:
            w, length = int(f.get("width") or 0), float(f.get("length") or 0)
        except (TypeError, ValueError):
            continue
        if length > 30 and (best is None or w > best[0]):
            best = (w, name, length)
    if best is None:
        raise ValueError("No usable MP4 in item")
    return f"https://archive.org/download/{item['identifier']}/{quote(best[1])}", best[2]


def _ua(user_agent: str | None) -> list[str]:
    """Kept for call-site compatibility; the User-Agent is sent by the HTTP bridge."""
    return []


def _src(url: str, user_agent: str | None = None) -> str:
    """FFmpeg input: remote URLs go through the local Python bridge (see httpbridge.py)."""
    from .httpbridge import local_url
    return local_url(str(url), user_agent)


def remote_info(url: str, user_agent: str | None = None) -> tuple[float, int, int]:
    """(duration, width, height) via FFmpeg's input inspection (one ranged request)."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", _src(url, user_agent)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    size = re.search(r"Video:.*?(?<![0-9a-fA-Fx])(\d{2,5})x(\d{2,5})(?![0-9])", p.stderr)
    if not dur or not size:
        last = [l for l in p.stderr.strip().splitlines() if l.strip()][-1:] if p.stderr else []
        raise ValueError("Remote video could not be inspected" + (f": {last[0][:120]}" if last else ""))
    h, m, s = dur.groups()
    return int(h) * 3600 + int(m) * 60 + float(s), int(size.group(1)), int(size.group(2))


def segment_start(duration: float, key: str) -> float:
    """Deterministic start between 15 % and 75 % of the film (skips titles/end slates)."""
    frac = 0.15 + 0.6 * (int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") / 65535)
    return max(0.0, min(duration - SEGMENT_SECONDS - 1, duration * frac))


def cut_segment(url: str, start: float, destination: Path, seconds: float = SEGMENT_SECONDS) -> Path:
    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme != "https" or host not in (NASA_HOST, "archive.org"):
        raise ValueError("Archive segment host not allowed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-reconnect", "1", "-reconnect_streamed", "1",
                    "-ss", f"{start:.2f}", "-i", _src(url), "-t", f"{seconds:.2f}", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                    str(destination)], check=True, capture_output=True, timeout=180)
    if destination.stat().st_size < 10_000:
        raise ValueError("Archive segment too small")
    return destination


FRAME_W, FRAME_H = 320, 240


def _remote_frame(url: str, at: float, user_agent: str | None = None):
    """One frame as raw RGB (no PNG/JPEG encoder needed: the bundled Linux FFmpeg
    build lacked one, so every frame check failed in CI with margin -1.0)."""
    from PIL import Image
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}",
                        "-i", _src(url, user_agent), "-frames:v", "1",
                        "-vf", f"scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=decrease,"
                               f"pad={FRAME_W}:{FRAME_H}:(ow-iw)/2:(oh-ih)/2",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, timeout=90)
    if len(p.stdout) < FRAME_W * FRAME_H * 3:
        detail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] if p.stderr else []
        raise ValueError("No frame" + (f": {detail[0][:120]}" if detail else ""))
    return Image.frombytes("RGB", (FRAME_W, FRAME_H), p.stdout[:FRAME_W * FRAME_H * 3])


def margin_for(image, positive, negative) -> float:
    """max(positive) − max(negative) CLIP similarity for free prompt lists (NaN: no model)."""
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is None:
        return float("nan")
    import torch
    model, preprocess, tokenizer = clip
    pos, neg = tuple(positive), tuple(negative)
    with torch.no_grad():
        img = torch.nn.functional.normalize(model.encode_image(preprocess(image).unsqueeze(0)), dim=-1)
        txt = torch.nn.functional.normalize(
            model.encode_text(tokenizer([f"a photo of {t}" for t in pos + neg])), dim=-1)
        sims = (img @ txt.T)[0].tolist()
    return round(max(sims[:len(pos)]) - max(sims[len(pos):]), 4)


def frame_margin_custom(path_or_url, at: float, positive, negative, user_agent: str | None = None) -> float:
    try:
        return margin_for(_remote_frame(str(path_or_url), at, user_agent), positive, negative)
    except (OSError, ValueError, subprocess.SubprocessError):
        return float("nan")


def sample_best(url: str, duration: float, positive, negative, key: str,
                seconds: float = SEGMENT_SECONDS, user_agent: str | None = None) -> tuple[float | None, float]:
    """Best of 3 spots in the middle of a remote video passing the content gate."""
    base = segment_start(duration, key)
    spots = sorted({max(0.0, min(duration - seconds - 1, base + d))
                    for d in (0.0, duration * 0.17, -duration * 0.17)})
    best = (None, -1.0)
    for at in spots:
        margin = frame_margin_custom(url, at + seconds / 2, positive, negative, user_agent)
        if margin == margin and margin > best[1]:
            best = (at, margin)
    return (best[0], best[1]) if best[1] >= MIN_MARGIN else (None, best[1])


def cut_segment_any(url: str, start: float, destination: Path, seconds: float,
                    *, allowed: tuple[str, ...], user_agent: str | None = None) -> Path:
    if urlparse(url).scheme != "https" or (urlparse(url).hostname or "").lower() not in allowed:
        raise ValueError("Segment host not allowed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *_ua(user_agent), "-reconnect", "1", "-reconnect_streamed", "1",
                    "-ss", f"{start:.2f}", "-i", _src(url, user_agent), "-t", f"{seconds:.2f}", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                    str(destination)], check=True, capture_output=True, timeout=180)
    if destination.stat().st_size < 10_000:
        raise ValueError("Segment too small")
    return destination


def frame_margin(image, source: str) -> float:
    """max(positive) − max(negative) CLIP similarity; > MIN_MARGIN means usable."""
    from .semantic import load_clip, semantic_enabled
    clip = load_clip() if semantic_enabled() else None
    if clip is None:
        return float("nan")
    import torch
    model, preprocess, tokenizer = clip
    pos, neg = POSITIVE[source], NEGATIVE[source]
    with torch.no_grad():
        img = torch.nn.functional.normalize(model.encode_image(preprocess(image).unsqueeze(0)), dim=-1)
        txt = torch.nn.functional.normalize(
            model.encode_text(tokenizer([f"a photo of {t}" for t in pos + neg])), dim=-1)
        sims = (img @ txt.T)[0].tolist()
    return round(max(sims[:len(pos)]) - max(sims[len(pos):]), 4)


def segment_ok(path: Path, source: str) -> bool:
    margins = []
    for at in (0.4, SEGMENT_SECONDS / 2, SEGMENT_SECONDS - 0.6):
        try:
            margins.append(frame_margin(_remote_frame(str(path), at), source))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"Archive segment frame unavailable: {type(exc).__name__}")
            return False
    return all(m == m and m > 0.0 for m in margins) and sum(margins) / len(margins) >= MIN_MARGIN


def best_offset(url: str, duration: float, source: str, key: str) -> tuple[float | None, float]:
    """Sample 3 spots in the film's middle; return the best one passing the content gate.

    Without OpenCLIP nothing passes: archive footage is never used unchecked.
    """
    base = segment_start(duration, key)
    spots = sorted({max(0.0, min(duration - SEGMENT_SECONDS - 1, base + d))
                    for d in (0.0, duration * 0.17, -duration * 0.17)})
    best = (None, -1.0)
    for at in spots:
        try:
            margin = frame_margin(_remote_frame(url, at + SEGMENT_SECONDS / 2), source)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"Archive frame unavailable at {at:.0f}s: {type(exc).__name__}: {str(exc)[:140]}")
            continue
        if margin != margin:
            print("Archive check needs OpenCLIP; model unavailable")
            break
        if margin == margin and margin > best[1]:  # skip NaN (no model)
            best = (at, margin)
    return (best[0], best[1]) if best[1] >= MIN_MARGIN else (None, best[1])


def fetch_archival(style: str | None, exclude: set[str], workdir: Path, *, run_key: str = "",
                   session=None, max_clips: int = MAX_CLIPS, attempts: int = 8) -> list[Video]:
    """Up to `max_clips` checked archival segments for the style; never raises."""
    if not enabled():
        return []
    session = session or requests.Session()
    found: list[Video] = []
    try:
        if style in NASA_QUERIES:
            queries = NASA_QUERIES[style]
            start = int.from_bytes(hashlib.sha256(run_key.encode()).digest()[:1], "big") % len(queries)
            items = search_nasa(queries[start:] + queries[:start], exclude, session=session)
        elif style in PRELINGER_QUERIES:
            items = search_prelinger(PRELINGER_QUERIES[style], exclude, session=session)
        else:
            return []
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"Archive search unavailable: {type(exc).__name__}")
        return []
    # Rotate so consecutive Reels with the same style use different films.
    shift = int.from_bytes(hashlib.sha256(f"{run_key}|items".encode()).digest()[:2], "big") % max(1, len(items))
    items = items[shift:] + items[:shift]
    for item in items[:attempts]:
        if len(found) >= max_clips:
            break
        try:
            if item["source"] == "nasa":
                url = nasa_media_url(item, session=session)
                duration, _w, _h = remote_info(url)
                credit, page = "NASA", f"https://images.nasa.gov/details/{quote(item['nasa_id'])}"
            else:
                url, duration = prelinger_media(item, session=session)
                credit = f"{item.get('archive') or 'Prelinger Archives'} (public domain)"
                page = f"https://archive.org/details/{item['identifier']}"
            if duration < SEGMENT_SECONDS + 5:
                continue
            start, margin = best_offset(url, duration, item["source"], f"{run_key}|{item['id']}")
            if start is None:
                print(f"Archive clip rejected by content check: {item['id']} ({margin})")
                continue
            path = cut_segment(url, start, workdir / f"archive_{len(found):02d}.mp4")
            # The segment itself may contain a hard cut (e.g. interview → planet):
            # every sampled frame of the actual clip must pass the content gate.
            if not segment_ok(path, item["source"]):
                print(f"Archive clip rejected after cut (mixed content): {item['id']}")
                path.unlink(missing_ok=True)
                continue
            public = item["source"] == "prelinger"
            found.append(Video(item["id"], item["source"], path=str(path), title=item["title"],
                               creator_name=credit, creator_url=page, query=item["query"], page_url=page,
                               licence=("Public domain (" + (item.get("archive") or "Internet Archive") + ")"
                                        if public else "NASA media usage guidelines (not copyrighted)"),
                               licence_url=(item.get("licence_url") or "https://creativecommons.org/publicdomain/mark/1.0/"
                                            if public else "https://www.nasa.gov/nasa-brand-center/images-and-media/"),
                               duration=SEGMENT_SECONDS))
            print(f"Archive clip: {item['id']} '{item['title'][:50]}' @ {start:.0f}s")
        except (requests.RequestException, ValueError, KeyError, OSError,
                subprocess.SubprocessError, json.JSONDecodeError) as exc:
            print(f"Archive clip skipped: {item.get('id')}: {type(exc).__name__}")
    return found
