"""Creative Directors (owner, 27 Nov: "dann kann ich im Verlauf den Creative Director
austauschen").

A director is ONE file in directors/<name>.json: themes (search words, roles, archive
share, text lines, music profile), the Coverr search words, signature-role queries, the
image prompts the style gate looks for, look (editing language), grade, effects, text
lines, cut pace. The pipeline modules (themes, style, stylegate, signature, hooktext,
reach) read their per-style tables from these files, so a new director is a new file —
no code change.

Which directors take turns: repo variable CARLECOOL_DIRECTORS (comma list, e.g.
"lana,night") or, when unset, every file with "active": true (in "order").

`world` is the base world of the shared code (reference images, cover style detection):
"lana" for both current directors; `variant` "night" switches the night-only checks
(daylight rejection, night grade). `references` names data/style-refs/<name>.json.

main.py calls `use(name)` once per Reel; afterwards `key(style, variant)` returns that
director for every table lookup. Without `use()` (tests, revisions of retired Rubin
Reels) the legacy mapping applies: variant night → "night", else the style name.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DIR = Path(os.getenv("CARLECOOL_DIRECTORS_DIR") or Path(__file__).resolve().parent.parent / "directors")
_CACHE: dict[str, dict] | None = None
_CURRENT: str | None = None


def load_all() -> dict[str, dict]:
    global _CACHE
    if _CACHE is None:
        out = {}
        for path in sorted(DIR.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(f"Director {path.name} unreadable:", type(exc).__name__)
                continue
            name = str(doc.get("name") or path.stem)
            out[name] = doc
        _CACHE = dict(sorted(out.items(), key=lambda kv: (int(kv[1].get("order") or 99), kv[0])))
    return _CACHE


def names() -> list[str]:
    return list(load_all())


def get(name: str | None) -> dict | None:
    return load_all().get(name or "")


def active() -> list[str]:
    """Directors that take turns (CARLECOOL_DIRECTORS overrides the files' "active")."""
    wanted = [n.strip().lower() for n in os.getenv("CARLECOOL_DIRECTORS", "").split(",") if n.strip()]
    if wanted:
        known = [n for n in wanted if n in load_all()]
        unknown = [n for n in wanted if n not in load_all()]
        if unknown:
            print("Unknown directors ignored:", ", ".join(unknown))
        if known:
            return known
    return [n for n, d in load_all().items() if d.get("active", True)] or names()


def decision(name: str) -> dict:
    """Style decision of a director (what style.analyze returns)."""
    d = get(name) or {}
    return {"style": d.get("world"), "variant": d.get("variant"), "director": name,
            "basis": "manual", "prompt": ""}


def use(name: str | None) -> None:
    global _CURRENT
    _CURRENT = name if get(name) else None


def current() -> str | None:
    return _CURRENT


def key(style: str | None, variant: str | None = None) -> str | None:
    """Table key for this Reel: the director in use, else the legacy style/variant key."""
    if _CURRENT is not None:
        return _CURRENT
    return "night" if variant == "night" else style


def table(field: str) -> dict[str, object]:
    """{director name: its `field`} for every director file that has it."""
    return {n: d[field] for n, d in load_all().items() if field in d}


def for_style(style: str | None, variant: str | None) -> str | None:
    """Director for a legacy (style, variant) pair, e.g. ("lana", "night") → "night"."""
    for n, d in load_all().items():
        if d.get("world") == style and d.get("variant") == variant:
            return n
    return None
