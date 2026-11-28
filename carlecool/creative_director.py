"""Unified Creative Director (owner brief 27 Nov, Phase 1).

`build_plan` writes ONE structured Creative Plan per Reel: the binding, reproducible record
of every creative decision and its reason — world, film idea, leitmotif, dominant and
complementary motifs, palette, light, camera language, musical arc, search strategy, hook,
transitions, effect rules and exclusions. It is stored in the review issue
(`creative_plan`) and printed in the log, so a Reel can be explained and re-made.

Phase 1 records the decisions the modules already make (directors/*.json, themes, music
analysis, hook, length, pipeline) in one place, on the #73 ("classic") basis the owner
chose. Later phases let the plan drive the material search and the storyboard (see
docs/implementation-plan.md). `ai_directions` (optional AI shots, off) stays here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib

PLAN_VERSION = 1


@dataclass
class CreativePlan:
    version: int
    director: str | None
    world: str | None
    variant: str | None
    theme: str | None
    film_idea: str
    leitmotif: str
    emotion: str
    dominant_motifs: list[str]
    complementary: list[str]
    palette: list[str]
    light: str
    camera: list[str]
    length_s: float
    musical_arc: dict
    search: list[str]
    hook: dict
    transitions: dict
    effects: dict
    exclusions: list[str]
    pipeline: str
    reasons: dict = field(default_factory=dict)
    trend: dict = field(default_factory=dict)  # Viral Integration Protocol (trend_compatibility.py)

    def as_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        return (f"Creative Plan v{self.version}: {self.director}/{self.theme} — {self.film_idea} · "
                f"leitmotif '{self.leitmotif}' · {self.length_s:.1f}s · pipeline {self.pipeline}")


def search_order(dominant: list[str], words: list[str], fixed: int = 2) -> list[str]:
    """Phase 2: the film idea leads the search — dominant motifs first, then the rest
    (car and flag, which every Reel needs, keep their place at the front)."""
    head = [w for w in words[:fixed]]
    rest = [w for w in words[fixed:]]
    lead = [w for w in dominant if w in rest]
    return head + lead + [w for w in rest if w not in lead]


def musical_arc(features) -> dict:
    """Sections the edit follows: hook (drop), structure changes, kicks count (measured)."""
    hook = float(getattr(features, "hook_at", 0.0) or 0.0)
    events = [round(float(t), 2) for t in (getattr(features, "structure_events", ()) or ())][:8]
    return {"bpm": round(float(getattr(features, "bpm", 0) or 0), 1), "hook_at": round(hook, 2),
            "structure_events": events, "kicks": len(getattr(features, "kicks", ()) or ()),
            "measured": "bpm, beats, kicks, energy (librosa)", "probabilistic": "mood, hook position"}


def build_plan(*, director: str | None, style_decision: dict, theme: str | None, features, length: float,
               keywords: list[str], roles: list[str] | tuple, hook_line: str, hook_strategy: str,
               pipeline: str, music_fit: float | None = None, length_reason: str = "") -> CreativePlan:
    from . import directors, style, themes
    d = directors.get(director) or {}
    world, variant = style_decision.get("style"), style_decision.get("variant")
    info = themes.get(world, variant, theme) or {}
    look = style.look(world, variant) or {}
    lines = list(info.get("lines") or [])
    leitmotif = lines[0] if lines else (d.get("summary") or "")[:80]
    film_idea = info.get("reference") or f"{info.get('label') or theme or 'free'} — {d.get('label') or world}"
    return CreativePlan(
        version=PLAN_VERSION, director=director, world=world, variant=variant, theme=theme,
        film_idea=str(film_idea), leitmotif=str(leitmotif), emotion=str(d.get("emotion") or ""),
        dominant_motifs=list(info.get("words") or [])[:6], complementary=[r for r in roles if r],
        palette=list(d.get("palette") or []), light=str(d.get("light") or ""), camera=list(d.get("camera") or []),
        length_s=round(float(length), 2), musical_arc=musical_arc(features), search=list(keywords),
        hook={"strategy": hook_strategy, "text": hook_line or None},
        transitions={"dissolve": look.get("dissolve"), "dissolve_below": look.get("dissolve_below"),
                     "bw_share": look.get("bw_share"), "cut_pace": d.get("pace")},
        effects={"light_leaks": bool(look.get("light_leaks")), "slowmo": look.get("slowmo"),
                 "chroma_shift": look.get("chroma_shift"), "grain_boost": look.get("grain_boost"),
                 "reach_fx": d.get("fx")},
        exclusions=list(d.get("exclusions") or []), pipeline=pipeline,
        reasons={"director": style_decision.get("basis"),
                 "theme": (f"music fit {round(music_fit, 2)} + weighted rotation" if music_fit is not None
                           else "weighted rotation / manual"),
                 "length": length_reason, "hook": "A/B test (hooktext / reach)",
                 "search": "theme words (+ car and flag)" if theme else "style words + profile"})


# ---------------------------------------------------------------- optional AI shots (off)
WORLDS = {
    "lana": ("warm muted Kodachrome, nostalgic coastal summer, authentic home movie",
             ("classic car on a coastal road", "a woman on a wooden porch", "vinyl record in golden light")),
    "night": ("muted blue and violet, cinematic 35mm night film, restrained neon",
              ("night drive through reflected street lights", "record player in a dim studio", "empty roadside motel at dusk")),
}


def ai_directions(style, variant, keywords, decision, edition):
    world = "night" if variant == "night" else (style if style in WORLDS else "lana")
    look, motifs = WORLDS[world]
    rotation = int(hashlib.sha256(str(edition).encode()).hexdigest()[:4], 16) % len(motifs)
    motifs = motifs[rotation:] + motifs[:rotation]
    return [f"{motif}; {look}; natural motion; no text, logos or distorted objects" for motif in motifs]
