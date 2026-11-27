"""Caption copy per style world: search line, occasional question, niche hashtags.

* First line stays "🎧 carl e cool - <title>" (song identity on every platform).
* A search line with words people type into TikTok/Instagram search
  ("instrumental beat for late night drives").
* Every third Reel (deterministic per run) a short question that invites comments.
* 3–4 rotating niche hashtags per world + #carlecool (instead of broad tags).
English, because the audience is international. The licence credits (Coverr,
Prelinger, Wikimedia …) are added by main.caption_for and stay complete.
The chosen variant is returned so performance learning can compare variants.
"""
from __future__ import annotations

import hashlib

SEARCH_LINES = {
    "lana": ("instrumental beat for late night drives", "dreamy instrumental for summer nights",
             "nostalgic beat for road trips", "melancholic instrumental for golden hour",
             "lofi americana beat for long drives"),
    "rubin": ("calm instrumental to focus", "minimal beat for late night studio sessions",
              "slow instrumental for quiet evenings", "warm analog beat to think to",
              "ambient instrumental for rainy days"),
    "night": ("instrumental for late night city drives", "night beat for empty streets",
              "neon night instrumental"),
}
QUESTIONS = ("Where would you play this?", "Turntable or MPC?", "Late night drive or early morning?",
             "Which city does this sound like?", "Vinyl or tape?", "What should the next one sound like?")
HASHTAGS = {
    "lana": ("#beatmaker", "#instrumental", "#producerlife", "#lofibeats", "#americana",
             "#nightdrive", "#vinyl"),
    "rubin": ("#instrumental", "#beatmaker", "#ambientmusic", "#producer", "#minimalmusic",
              "#analogsynth", "#studiolife"),
}
QUESTION_EVERY = 3
TAGS_PER_POST = 4


def _pick(options, key: str):
    return options[int.from_bytes(hashlib.sha256(key.encode()).digest()[:2], "big") % len(options)]


def variant(style: str | None, variant_name: str | None, run_key: str) -> dict:
    world = style if style in HASHTAGS else "lana"
    lines = SEARCH_LINES["night"] if variant_name == "night" else SEARCH_LINES[world]
    pool = list(HASHTAGS[world])
    start = int.from_bytes(hashlib.sha256(f"{run_key}|tags".encode()).digest()[:2], "big") % len(pool)
    tags = (pool[start:] + pool[:start])[:TAGS_PER_POST]
    ask = int.from_bytes(hashlib.sha256(f"{run_key}|ask".encode()).digest()[:1], "big") % QUESTION_EVERY == 0
    return {"world": world, "search_line": _pick(lines, f"{run_key}|line"),
            "question": _pick(QUESTIONS, f"{run_key}|q") if ask else "",
            "hashtags": ["#carlecool", *tags]}


SPOTIFY_LINE = "🟢 Out now on Spotify:"


def links() -> dict:
    """Owner's public streaming links (data/links.json)."""
    import json
    from pathlib import Path
    try:
        return json.loads(Path("data/links.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def head(song_label: str, chosen: dict) -> str:
    text = f"🎧 {song_label}\n"
    if links().get("spotify_artist"):
        # owner, 27 Nov: the Spotify link directly under the video. TikTok / Instagram show
        # it as text (not clickable there); the clickable one is the bio link.
        text += f"{SPOTIFY_LINE} {links()['spotify_artist']}\n"
    text += f"{chosen['search_line']}\n"
    if chosen.get("question"):
        text += chosen["question"] + "\n"
    return text


def tail(chosen: dict) -> str:
    return " ".join(chosen["hashtags"])
