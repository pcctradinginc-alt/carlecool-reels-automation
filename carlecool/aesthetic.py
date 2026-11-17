"""Editorial style brief for licensed stock, not a generative-video model."""
STYLE_NAME = "CarleCool — Rubin / Analog Studio / Americana Melancholy / 90s Skate"
EDIT_PLAN = ("Still backlit nature and real tactile textures -> MPC-style sampler / vinyl / "
             "recording work -> faded California highway, motel and palm silhouettes -> "
             "restrained 90s skate contrast. Warm desaturated Super 8; little neon or glamour.")


def editorial_brief(mood, energy, bpm):
 return {"name": STYLE_NAME, "edit_plan": EDIT_PLAN, "mood": mood,
         "tempo": "kinetic" if energy >= .65 or bpm >= 135 else "contemplative",
         "note": "Creative direction; only licensed stock and original music used."}
