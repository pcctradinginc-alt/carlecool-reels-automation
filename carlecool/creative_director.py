"""One bounded creative brief for generated footage; no artist media leaves the runner."""
import hashlib

WORLDS = {
    "lana": ("warm muted Kodachrome, nostalgic coastal summer, authentic home movie",
             ("classic car on a coastal road", "friends on a wooden porch", "vinyl record in golden light")),
    "rubin": ("earth tones, quiet natural light, understated analog documentary",
              ("hands on a vintage analog mixing console", "wind through coastal grass", "classic off-road vehicle on a rural road")),
    "night": ("muted blue and violet, cinematic 35mm night film, restrained neon",
              ("night drive through reflected street lights", "record player in a dim studio", "empty roadside motel at dusk")),
}

def ai_directions(style, variant, keywords, decision, edition):
    world = "night" if variant == "night" else style
    look, motifs = WORLDS.get(world, WORLDS["rubin"])
    # Only static, public-safe motifs are sent to the external Space.
    rotation = int(hashlib.sha256(str(edition).encode()).hexdigest()[:4], 16) % len(motifs)
    motifs = motifs[rotation:] + motifs[:rotation]
    return [f"{motif}; {look}; natural motion; no text, logos or distorted objects" for motif in motifs]
