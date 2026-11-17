# CarleCool — Visual Direction / Master Prompt

**Style & Aesthetic:** A Gen-Z hyper-curated hybrid aesthetic: Analog-Digital Nostalgia × Corecore × Zen Minimalism. Ultra-clean product-ad composition meets meditative Malibu recording-retreat stillness, natural wood, white rooms and California coastlines; 1960s/70s nostalgic Americana, raw 1990s skate culture, and early-2000s Y2K digicam rawness. Aesthetic touchstones include Rick Rubin’s Shangri-La retreat and Lana Del Rey-era coastal melancholia, without copying celebrity likenesses or protected brand designs.

**Cinematography & Camera:** Long static, wide, meditative landscape and white-room shots interrupted by extreme low-angle fisheye skate shots against pure white sky; shaky 2005 consumer digicam and direct night flash; Super 8mm, CRT/VHS scanlines, whip-pans, crash zooms, 0.5x ultra-wide perspective and motion blur.

**Lighting & Colors:** Warm Malibu sunlight, off-whites, natural driftwood, brushed silver and deep shadow; golden-hour palm silhouettes, cherry red, faded pastel blue and blue/purple neon nights.

**Subjects, Props & Styling:** Gen-Z skaters in baggy thrifted 1990s fashion (oversized boxy white/black tees, dark denim, crew socks, retro skate shoes, beanies, wired white earbuds, rimless sunglasses), contrasted with barefoot, meditative artist moments. Skateboards covered in stickers, silver laptop, analog reel-to-reel recorder, iced coffee, vintage motels and classic cars.

**Graphic/UX/Corecore:** Chaotic-yet-clean overlays: fine white motion-tracking lines, small data coordinates, fictional phone-recording UI frames, minimalist fine sans-serif lyric captions **only when rights-cleared**, bento grids, occasional silent-looking white/black title cards. Never show personal data or misleading UI.

## Editing rules

- **Signature contrast:** calm Malibu / white room -> kinetic skate fisheye -> Y2K night flash / analogue -> minimalist calm. Empty reflective frames are as important as chaotic cuts.
- Cut points should follow **music** first, using beat estimates as guidance. Mix slower contemplative scenes with sharp transitions as footage allows.
- Color anchors: warm off-white, muted pastel blue, driftwood and silver; accents in cherry red and purple/blue neon.
- Prefer licensed original-looking scenes, not a collage of random popular footage. Stock queries in `carlecool/keywords.py` and selection in `carlecool/video.py` implement three contrasting search lanes.
- The existing renderer uses sourced footage and FFmpeg; it does **not** yet generate footage with AI, perform frame-level aesthetic vision classification, or automatically add all proposed overlays. This document is also a ready-to-copy style prompt if a licensed generative tool is later added.
- Screenshots mentioned by filename in the original brief were not supplied as image assets.

## v2 visual identity — CarleCool Rubin / Analog / Americana / Skate

**Primary hierarchy:** Rick Rubin quiet nature and creative stillness → tactile analog studio / Akai MPC 2000 XL references → cinematic melancholic California Americana → raw 1990s skateboard motion. Y2K and neon are accent languages, not the dominant aesthetic. Avoid direct celebrity imitation, protected material, fake documentary claims or fabricated footage authenticity.

### 1. Analog feeling / imperfection

Macro textures of guitar wood grain, vinyl grooves and spinning turntables, dusty cassettes, worn paper notebooks, drum machine pads, an MPC 2000 XL-style sampler, analog mixing-console faders and cables. Naturally imperfect camera moments, restrained lens softness and imperfect available light. Use subtle Super 8 grain, faded colors, mild film wear, soft contrast and gentle transitions. **Do not deliberately fake ownership of equipment shown in licensed stock footage.**

### 2. Rick Rubin calm / organic nature

Sunlight filtering through trees or studio windows; water, wind, leaves, earth and a still sky. Warm off-white, driftwood, deep chiaroscuro natural shadows. Tripod-static compositions, eyes closed and a solitary contemplative musician, creative flow, barefoot or socks on wood floors. Long meditative holds and quiet landscape frames. Avoid flashy ringlight looks and restless phone-camera motion.

### 3. Process before perfection

Hands turning synth knobs, tapping sampler pads, playing strings or annotating lyrics in a notebook. Unstaged work and acoustic concentration, subdued tungsten or window light. A documentary seated angle rather than a wide-angle selfie; natural personal presence only with properly released footage.

### 4. Lana-associated Americana melancholy — interpreted independently

Mood: cinematic loneliness, nostalgic West Coast summer, romantic longing, classic American road-trip imagery and faded Hollywood elegance. Shoot empty highways, California palm silhouettes, sun-faded motel signs, diners, vintage car interiors, open asphalt, dusk, night drives and summer daydreams. Old home-video Super 8 language; imperfect color drift, soft highlight bloom, muted warm pastels and dusty shadows. Old Hollywood is an *atmosphere*, not a copy of any singer's face, costumes, music videos, trademark look or persona. Glamour is restrained; avoid over-the-top coquette cosplay, melodramatic quote cards, flag motifs and exaggerated "sad girl" clichés.

### 5. 1990s California skate

Authentic low-angle fisheye skate, sun-bleached asphalt, old sneakers, oversized thrifted T-shirts and denim, 90s camcorder proximity, slow motion as punctuation. Use energetic cuts sparingly against quiet narrative scenes; avoid making the entire Reel a skate compilation.

### 6. Y2K / Corecore accents

Direct-flash digicam texture, CRT scanlines, occasional archival-looking consumer video, bento-like arrangements and sparse fine typography. Cherry red / washed pale blue / purple-blue night lighting only for accents. Avoid generic over-neonized party stock or imitation software screenshots.

### 7. Editorial rules and negatives

- Static beats unstable motion; real textures beat digital perfection; warm/window light beats harsh ringlight
- Calm nature and studio are the centre; Americana melancholic framing brings emotional depth; skateboard footage adds short moments of movement
- Neutral/off-white, warm wood, desaturated pastel blue; low glare, subdued saturation, soft contrast, grain as an optional intensity control
- Prioritize scene continuity and identifiable subject relevance over stock popularity, but recognize Coverr API does not supply reliable visual subject classification
- Lyrics require separate rights clearance; no celebrity images or likeness imitation; no unauthorized brand logos or personal information
- Actual licensed-footage selection runs **three searches per Reel**; weights control probabilities across Reels, not a guaranteed frame-level ratio. A textual MPC prompt may return generic studio clips without a visual-understanding model

### Final reusable master prompt (English)

> Create a 9:16 original, restrained cinematic mini-film for CarleCool electronic music. Combine Rick Rubin-like meditative recording-retreat calm with closeups of tactile analog songwriting tools, vintage sampler/MPC-style hands, vinyl, tape, guitar wood grain and handwritten notebooks. Intercut still sunlit trees, quiet rivers and warm minimalist white studios with old California highway, palm-tree golden-hour silhouettes, faded motel signs, a lonely night drive and understated early-Hollywood nostalgia. Romantic melancholy and 1960s–70s Americana atmosphere should be independent and original, not a direct impersonation or reconstruction of Lana Del Rey imagery. Occasionally interrupt the calm with raw 1990s West Coast skateboard fisheye shots and 2000s digicam/Super 8 imperfections. Use natural dramatic shadows, worn warm off-white, driftwood, muted blues and grain, with restrained cherry-red or purple-neon accents. Favor static tripod frames, subtle light leaks and real process over over-polished reels; no ringlights, influencer selfies, high-gloss fashion, direct celebrity likenesses, copyrighted music video frames, quote cards or cheap neon glitches. Let the music determine exact cut rhythm, maintain still moments and an emotionally legible beginning and ending.

See [Creative Control](creative-control.md) for adjustable weights, presets, revision comments and the no-publish Gmail workflow.
