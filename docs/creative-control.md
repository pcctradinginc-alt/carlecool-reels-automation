# CarleCool Creative Control v2

This is an **interpretable, deterministic creative director**, not generative video or an image-recognition AI. It uses three weighted stock-footage queries, Coverr metadata and FFmpeg grading. A prompt such as "MPC 2000 XL" guides a **music-equipment search**, but does not guarantee that the resulting clip actually contains that model.

## Default CarleCool Visual DNA

| Visual lane | Default share (query selection probability, NOT exact screen time) |
| --- | ---: |
| Rick Rubin / serene nature and sunlight | 28% |
| Analogue studio / MPC 2000 XL / tactile creative process | 22% |
| Americana melancholy / vintage Hollywood / coast | 20% |
| 1990s California skateboard / fisheye | 18% |
| Y2K digicam / VHS / Corecore | 7% |
| Urban night / restrained neon | 5% |

Defined at `data/creative-profile.json`; presets and strict parser at `carlecool/creative.py`. Weights are normalized and seed deterministic per track/revision. Style feedback is stored as public-only preference data after a successfully delivered revised email. No user account secrets are stored.

Legacy presets (the Rubin world is retired since 27 Nov; styles now come from `directors/`): `rubin_analog_lana_skate` (default), `rubin_lana`, `sad_summer_americana`, `analog_california`, `skate_melancholy`, `rubin_calm`, `analog_studio`, `corecore_hybrid`, `minimal_apple_rubin`.

## Direct feedback from the approval email

Open the clearly labeled **Freigabe & Überarbeitung öffnen** link. That opens a **public GitHub approval Issue**, where you must sign in as the owner to comment. No button publishes automatically.

- `/revise mehr natur, weniger skate` – new search balance
- `/revise more_mpc` – prioritizes vintage sampler/studio visuals
- `/revise more_analog` – increases desaturation and grain
- `/revise more_lana` or `/revise more_americana` – coastal road nostalgia, summer melancholy, palm silhouettes, motels
- `/revise more_super8` – film-grain/analog emphasis
- `/revise slower_cuts` or `/revise faster_cuts` – changes duration between cuts
- `/revise first_30_seconds` – music starts at the beginning
- `/revise preset_rubin_lana` – switch to a new saved style
- `/revise no_faces` – avoid portraits via query strategy; cannot guarantee no faces without frame-level visual inspection
- `/reject` – close without posting
- `/approve` (or `/publish`) – only after a separate publish-enabled secret + rights clearance; still no auto-posting

The text interpreter recognizes a deliberately small vocabulary of supported German phrases and explicit commands. Unsupported text **fails safely** rather than pretending to be understood. The revision workflow supports up to five versions per original proposal; old Issue approval is deactivated while the next version renders. The new MP4 is sent privately via Gmail, gets a new GitHub Issue and SHA-256, and the old Issue is closed. Nothing is stored as a public GitHub media artifact.

## Production behavior

1. Identify SoundCloud track from latest 20; use published RSS audio for owned artist music.
2. Choose excerpt, based on loudness or first 30 seconds.
3. Sample three distinct style categories according to user weights and music energy.
4. Map conceptual phrases to **short Coverr API search terms** (e.g. MPC -> music, sea -> beach, skate -> skateboarding, Americana sunset -> sunset). Search results are not independently verified by a vision model.
5. Download and account for Coverr clips; alternate results from search lanes.
6. Render at 9:16 with user-selected cut pace (slow / medium / fast) and analogous FFmpeg saturation/contrast/grain intensity 0–100%.
7. Email exact MP4 with a direct clickable review Issue link. The manual approval gate is unchanged.

See [visual-direction.md](visual-direction.md) for complete creative language, color references and negative rules. User feedback changes future query weights, but CarleCool does not train a neural model on ratings. No promise of exact object detection, visual continuity or free cloud AI-generated video.

## Optional genuine AI-generated scenes (free HF ZeroGPU experiment)

The official Lightricks LTX-2.3 Space has generated and validated an **actual two-second clip** from GitHub Actions with no paid inference. Use `/revise ai_video` or `/revise mehr ki` on an existing GitHub approval Issue to regenerate its song's Reel with **at most one actual AI video clip** and Coverr footage for the rest. Style feedback remembers AI preferences for future proposals. Use `/revise coverr_only` to disable future AI clips. The current repository default remains **off** until the owner expressly opts in via a revision; the installed Gradio API adapter calls no paid endpoint. If the free quota is exhausted or the Space fails, the original Coverr footage pipeline takes over automatically.

AI media are temporary, transmitted only via the private Gmail preview and never put in public GitHub artifacts. The external provider receives only the public-safe art-direction prompt, not songs or videos. AI-inclusive Instagram publication requires the additional, independently controlled `AI_VIDEO_PUBLISH_LICENSE_CONFIRMED=true` GitHub Secret plus pre-existing human approval and Coverr rights clearance. The model's license and terms must be reviewed before activating it.
