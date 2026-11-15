"""Editorial search vocabulary supplied by CarleCool, ranked by audio mood and energy."""
from __future__ import annotations

VIDEO_KEYWORDS = [
    "skateboarding night city", "skateboarder street trick slow motion",
    "skateboard wheels asphalt close up", "skatepark sunset silhouette",
    "skater neon lights urban", "fisheye skateboard filming",
    "night skate downtown empty street", "skateboarder jumping stairs",
    "graffiti artist spraying wall night", "colorful street art mural urban",
    "spray paint cans close up street", "graffiti underpass shadows",
    "urban mural neon light reflection", "street art alley aesthetic",
    "stencil graffiti concrete wall", "gen z streetwear fashion night",
    "friends walking city night neon", "analog film camera flash party",
    "vintage thrift store aesthetic", "urban rooftop hangout sunset",
    "headphones music city walk night", "late night convenience store neon",
    "sneakers walking urban pavement", "urban alleyway neon rain",
    "subway train window night blur", "empty basketball court night lights",
    "brutalist concrete architecture night", "streetlamp fog night aesthetic",
    "rooftop city skyline night", "night drive city lights bokeh",
    "car drifting smoke night", "tunnel speed light trails",
    "bmx rider night street", "motorcycle night city neon",
    "fpv drone city night", "90s camcorder aesthetic street",
    "vhs glitch retro neon", "rain on window night city",
    "vinyl record spinning close up", "liquid chrome 3d abstract loop",
]

MOOD_GROUPS = {
    "nightdrive": ["night drive city lights bokeh", "urban alleyway neon rain",
                   "skateboarding night city", "tunnel speed light trails",
                   "subway train window night blur", "motorcycle night city neon",
                   "bmx rider night street", "fpv drone city night",
                   "skater neon lights urban", "car drifting smoke night"],
    "calm": ["rain on window night city", "rooftop city skyline night",
             "streetlamp fog night aesthetic", "vinyl record spinning close up",
             "urban rooftop hangout sunset", "skatepark sunset silhouette",
             "90s camcorder aesthetic street", "vintage thrift store aesthetic"],
    "cinematic": ["graffiti artist spraying wall night", "urban mural neon light reflection",
                  "friends walking city night neon", "brutalist concrete architecture night",
                  "analog film camera flash party", "night skate downtown empty street",
                  "gen z streetwear fashion night", "liquid chrome 3d abstract loop"],
}


def select_keywords(mood: str, energy: float = 0.5, bpm: float = 120, *, seed: str = "", limit: int = 3) -> list[str]:
    """Three deterministic diverse queries; no randomness or uncontrolled API fanout."""
    if limit < 1:
        return []
    group = list(MOOD_GROUPS.get(mood, MOOD_GROUPS["cinematic"]))
    if energy >= .65 or bpm >= 135:
        fast = ["skateboarder jumping stairs", "car drifting smoke night", "tunnel speed light trails",
                "skateboarder street trick slow motion"]
        group = fast + [x for x in group if x not in fast]
    # Rotate per track so music with the same mood does not always use the same queries.
    import hashlib
    offset = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % len(group) if seed else 0
    return (group[offset:] + group[:offset])[:limit]
