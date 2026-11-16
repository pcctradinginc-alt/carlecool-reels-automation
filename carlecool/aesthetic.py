"""Editorial style brief for licensed stock, not a generative-video model."""
STYLE_NAME = "Analog-Digital Nostalgia × Corecore × Zen Minimalism"
EDIT_PLAN = "Malibu stillness -> California skate fisheye -> Y2K analog flash -> purple/blue neon; beat-led contrast"


def editorial_brief(mood, energy, bpm):
 return {"name": STYLE_NAME, "edit_plan": EDIT_PLAN, "mood": mood,
         "tempo": "kinetic" if energy >= .65 or bpm >= 135 else "contemplative",
         "note": "Creative direction; only licensed stock and original music used."}
