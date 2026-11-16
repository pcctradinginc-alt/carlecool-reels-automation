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
    "minimalist white room natural wood sunlight", "empty california coastline warm sunrise",
    "malibu beach empty cinematic wide shot", "meditation artist floor natural light",
    "pacific highway vintage car golden hour", "palm tree sunset silhouette super 8 film",
    "1960s americana roadside motel vintage", "vintage red convertible california desert",
    "fisheye low angle skateboard white sky", "90s california skatepark fisheye film",
    "y2k digital camera direct flash friends", "early 2000s camcorder skate street",
    "sony cybershot flash night party", "silver laptop wired earphones aesthetic",
    "reel to reel analog tape machine studio", "brushed silver product minimalist white",
    "vhs crt television static scanlines", "retro film grain coastal highway",
    "empty white architectural room shadows", "neon purple blue urban night reflections",
]

VISUAL_LANES = {
 "stillness": ["minimalist white room natural wood sunlight", "empty california coastline warm sunrise", "malibu beach empty cinematic wide shot", "meditation artist floor natural light", "empty white architectural room shadows"],
 "action": ["fisheye low angle skateboard white sky", "90s california skatepark fisheye film", "skateboarder street trick slow motion", "skateboarding night city", "skateboarder jumping stairs"],
 "nostalgia": ["palm tree sunset silhouette super 8 film", "y2k digital camera direct flash friends", "early 2000s camcorder skate street", "sony cybershot flash night party", "1960s americana roadside motel vintage", "retro film grain coastal highway"],
 "night": ["neon purple blue urban night reflections", "night drive city lights bokeh", "subway train window night blur", "urban alleyway neon rain", "late night convenience store neon"],
}


def select_keywords(mood: str, energy: float = 0.5, bpm: float = 120, *, seed: str = "", limit: int = 3) -> list[str]:
 """Deterministic contrast: stillness versus kinetic action versus analogue nostalgia."""
 if limit < 1:
  return []
 import hashlib
 fast = energy >= .65 or bpm >= 135
 lanes = (["action", "stillness", "nostalgia"] if fast else ["stillness", "nostalgia", "action"] if mood == "calm" else ["night", "stillness", "nostalgia"])
 result = []
 for lane in lanes:
  choices = VISUAL_LANES[lane]
  index = int.from_bytes(hashlib.sha256(f"{seed}:{mood}:{lane}".encode()).digest()[:4], "big") % len(choices)
  result.append(choices[index])
 return result[:min(3, limit)]
