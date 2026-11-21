"""Wikimedia Commons: extra free footage and FSA/OWI Kodachrome photos.

* Category-based (not free text): curated categories per style / role.
* Licence gate: Public domain / CC0 / CC BY only. CC BY-SA (share-alike would bind the
  whole Reel), NC and ND are rejected, as is any file with a "Restrictions" notice
  (personality rights, trademarks, insignia …).
* Quality gate: ≥ 720 px tall, OpenCLIP content check on several frames (same gate as
  archives.py), low-res footage is shown framed by the renderer.
* Photos (FSA/OWI 1939–44 Kodachromes, public domain) become slow Ken-Burns shots.
* Polite API use: one request per category, pauses, Retry-After on HTTP 429, then skip.
  User-Agent from WIKIMEDIA_USER_AGENT (Wikimedia asks for a contact); a generic default
  without personal data is used otherwise and may be throttled.
CC BY credits ("<artist> / Wikimedia Commons, CC BY x.0") go into the caption.
"""
from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlparse

import requests

from .video import Video

API = "https://commons.wikimedia.org/w/api.php"
MEDIA_HOST = "upload.wikimedia.org"
DEFAULT_UA = "ReelBuilder/1.0 (automated short-video montage; python-requests)"
SEGMENT_SECONDS = 7.0
PHOTO_SECONDS = 5.0

CATEGORIES = {
    "lana": [("Color photographs from the Farm Security Administration", "photo"),
             ("Videos of horses", "video"), ("Time-lapse videos of sunsets", "video")],
    "rubin": [("Time-lapse videos of sunsets", "video")],
    "skater": [("Videos of skateboarding", "video")],
}
POSITIVE = {
    "lana": ("a vintage color photo of an american highway, car, diner or small town",
             "a horse in an open landscape", "a sunset over a calm landscape"),
    "rubin": ("a calm sunset over the sea or a landscape", "a quiet natural landscape"),
    "skater": ("a skateboarder riding a skateboard, face not visible",
               "feet on a skateboard on asphalt"),
}
SENSITIVE = ("slave", "lynch", "klan", "segregat", "internment", "camp", "relief client",
             "borrower", "sharecropper", "migrant", "poverty", "destitute", "jail", "funeral")
NEGATIVE = ("a portrait of a person looking at the camera", "a document, map or text",
            "a black and white photo", "a logo or graphic", "a black or blank screen",
            "a crowd at an event", "a car crash or an accident")


def enabled() -> bool:
    return os.getenv("CARLECOOL_WIKIMEDIA", "true").strip().lower() in ("true", "1", "yes", "on")


def user_agent() -> str:
    return os.getenv("WIKIMEDIA_USER_AGENT", "").strip() or DEFAULT_UA


def _session(session=None):
    session = session or requests.Session()
    session.headers["User-Agent"] = user_agent()
    return session


def license_ok(name: str, restrictions: str) -> bool:
    low = (name or "").strip().lower()
    if restrictions and restrictions.strip():
        return False
    if any(tag in low.replace("-", " ").split() for tag in ("sa", "nc", "nd")):
        return False
    return (low.startswith(("public domain", "cc0", "pd")) or low.startswith("cc by"))


def _text(value) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def category_files(category: str, *, session=None, limit: int = 60, pause: float = 1.5) -> list[dict]:
    """Files of one category with licence, size and URLs; [] when throttled/unavailable."""
    session = _session(session)
    params = {"action": "query", "generator": "categorymembers", "gcmtitle": f"Category:{category}",
              "gcmtype": "file", "gcmlimit": limit, "prop": "imageinfo",
              "iiprop": "size|mime|extmetadata|url", "iiurlwidth": 1920,
              "iiextmetadatafilter": "LicenseShortName|Restrictions|Artist",
              "format": "json", "maxlag": 5}
    for attempt in range(2):
        time.sleep(pause)
        r = session.get(API, params=params, timeout=30)
        if r.status_code == 429 and attempt == 0:
            time.sleep(min(30.0, float(r.headers.get("Retry-After") or 10)))
            continue
        if r.status_code != 200:
            print(f"Wikimedia '{category}': HTTP {r.status_code}, skipped")
            return []
        break
    try:
        pages = r.json().get("query", {}).get("pages", {}).values()
    except ValueError:
        return []
    out = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _text((meta.get("LicenseShortName") or {}).get("value"))
        restr = _text((meta.get("Restrictions") or {}).get("value"))
        url = str(info.get("url") or "")
        if not license_ok(lic, restr) or urlparse(url).hostname != MEDIA_HOST:
            continue
        # Historical captions (e.g. 1940s FSA) can contain slurs or depict real people
        # in sensitive contexts — never use those in promotional Reels.
        from .archives import PRELINGER_EXCLUDE, _blocked
        if _blocked(str(page.get("title", "")).lower(), PRELINGER_EXCLUDE + SENSITIVE):
            continue
        out.append({"id": "wm-" + hashlib.sha1(page.get("title", "").encode()).hexdigest()[:12],
                    "title": str(page.get("title", ""))[5:120], "license": lic,
                    "artist": _text((meta.get("Artist") or {}).get("value"))[:80],
                    "page": str(info.get("descriptionurl") or ""), "url": url,
                    "thumb": str(info.get("thumburl") or ""), "mime": str(info.get("mime") or ""),
                    "width": int(info.get("width") or 0), "height": int(info.get("height") or 0)})
    return out


def credit_line(item: dict) -> str:
    if item["license"].lower().startswith("cc by"):
        who = item["artist"] or "Unknown author"
        return f"{who} / Wikimedia Commons ({item['license']})"
    return "Wikimedia Commons (public domain)"


def _ken_burns(image_url: str, destination: Path, key: str) -> Path:
    """Slow zoom (and gentle drift) over a still photo: 5 s, 24 fps, 1920 px wide."""
    if urlparse(image_url).hostname != MEDIA_HOST:
        raise ValueError("Unexpected Wikimedia image host")
    zoom_in = int(hashlib.sha256(key.encode()).digest()[0]) % 2 == 0
    frames = int(PHOTO_SECONDS * 24)
    z = "min(1+0.0011*on,1.13)" if zoom_in else "max(1.13-0.0011*on,1.0)"
    destination.parent.mkdir(parents=True, exist_ok=True)
    from .httpbridge import local_url
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", local_url(str(image_url), user_agent()), "-vf",
                    f"scale=3840:-2,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    f":d={frames}:s=1920x1440:fps=24,format=yuv420p",
                    "-frames:v", str(frames), "-c:v", "libx264", "-crf", "16", "-preset", "veryfast",
                    str(destination)], check=True, capture_output=True, timeout=180)
    return destination


def fetch_wikimedia(role: str, exclude: set[str], workdir: Path, *, run_key: str = "",
                    max_clips: int = 2, attempts: int = 6, session=None) -> list[Video]:
    """Checked Commons clips for a style ("lana", "rubin") or role ("skater"); never raises."""
    if not enabled() or role not in CATEGORIES:
        return []
    from .archives import MIN_MARGIN, cut_segment_any, remote_info
    from .archives import frame_margin_custom, sample_best
    session = _session(session)
    pool: list[tuple[dict, str]] = []
    try:
        for category, kind in CATEGORIES[role]:
            pool += [(item, kind) for item in category_files(category, session=session)
                     if item["id"] not in exclude]
    except (requests.RequestException, ValueError) as exc:
        print(f"Wikimedia unavailable: {type(exc).__name__}")
        return []
    if not pool:
        return []
    shift = int.from_bytes(hashlib.sha256(f"{run_key}|{role}".encode()).digest()[:2], "big") % len(pool)
    pool = pool[shift:] + pool[:shift]
    positive, negative = POSITIVE[role], NEGATIVE
    found: list[Video] = []
    for item, kind in pool[:attempts * 2]:
        if len(found) >= max_clips or attempts <= 0:
            break
        try:
            target = workdir / f"wm_{role}_{len(found):02d}.mp4"
            if kind == "photo":
                if not item["thumb"] or min(item["width"], item["height"]) < 900:
                    continue
                attempts -= 1
                _ken_burns(item["thumb"], target, f"{run_key}|{item['id']}")
            else:
                if not item["mime"].startswith("video/") or item["height"] < 720:
                    continue
                attempts -= 1
                duration, _w, _h = remote_info(item["url"], user_agent())
                if duration < SEGMENT_SECONDS + 2:
                    continue
                start, margin = sample_best(item["url"], duration, positive, negative,
                                            f"{run_key}|{item['id']}", SEGMENT_SECONDS, user_agent())
                if start is None:
                    print(f"Wikimedia clip rejected by content check: {item['title'][:50]} ({margin})")
                    continue
                cut_segment_any(item["url"], start, target, SEGMENT_SECONDS, allowed=(MEDIA_HOST,),
                                user_agent=user_agent())
            margins = [frame_margin_custom(target, at, positive, negative)
                       for at in (0.4, 2.5, (PHOTO_SECONDS if kind == "photo" else SEGMENT_SECONDS) - 0.6)]
            if not all(m == m and m > 0 for m in margins) or sum(margins) / len(margins) < MIN_MARGIN:
                print(f"Wikimedia clip rejected after cut: {item['title'][:50]}")
                target.unlink(missing_ok=True)
                continue
            found.append(Video(item["id"], "wikimedia", path=str(target), title=item["title"],
                               creator_name=credit_line(item), creator_url=item["page"],
                               query=f"wikimedia:{role}",
                               duration=PHOTO_SECONDS if kind == "photo" else SEGMENT_SECONDS))
            print(f"Wikimedia {kind}: {item['title'][:60]} ({item['license']})")
        except (requests.RequestException, ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            print(f"Wikimedia clip skipped: {item.get('title', '')[:40]}: {type(exc).__name__}: {str(exc)[:140]}"
                  + ("" if os.getenv("WIKIMEDIA_USER_AGENT") else
                     " (tip: set WIKIMEDIA_USER_AGENT with a contact; Wikimedia throttles anonymous clients)"))
    return found
