# Implementation plan – Autonomous Cinematic Production System

Basis: `docs/audit-2026-11-27.md`.
- Branch: `dev/cinematic-system`, no merge to main without the owner's approval.
- Every phase is its own commit series with tests and can be rolled back on its own (feature flag where behaviour changes).
- Principle: **improve and merge existing modules, do not build parallel ones.**

## Phase 1 – Creative Plan as the single decision instance

| File | Change |
|---|---|
| `carlecool/creative_director.py` | Becomes `plan(song, features, cover, director, library, history, decisions, performance) → CreativePlan`, a dataclass with these fields: world, film idea, leitmotif, dominant + 2–3 complementary motif worlds, palette, light, camera language, shot sizes, musical arc, storyboard slots (function per slot: hook / establishing / atmosphere / development / contrast / accent / climax / resolution / loop), search strategy, hook strategy, transition strategy, effect rules, exclusions. **Every hash choice becomes a reasoned decision**, and the reason is stored in the plan. `ai_directions` stays as a small function of it. |
| `carlecool/main.py` | Gets the plan instead of scattered `themes.*`/`style.*`/`reach.*`/`hooktext.*` calls. Remove the dead search path (A1). The plan goes into the issue data (`creative_plan`) → reproducible. |
| `carlecool/style.py`, `themes.py` | Kept only as data access to `directors/*.json`. Remove `music_style`/`decide`/cover scores for Rubin (A3). Migrate the Rubin tables to `directors/legacy-rubin.json` (`active: false`) so old revisions keep working. |
| `directors/*.json` | Remove the field `weights` (A4) or turn it into the motif-world weights of the plan. |
| `README.md`, `docs/creative-control.md` | Update to Lana / Night / directors (G). |
| Dead code (H) | Remove after a test confirms it is unused. |
| Tests | Plan is reproducible (same inputs → same plan), every field is set, the reasons are not empty, a Rubin revision still renders. |

## Phase 2 – Material follows the plan

| File | Change |
|---|---|
| `carlecool/creative_director.py` | Search words come from the **open storyboard slots** (e.g. "detail · analog gear · night" → `drum machine`, `vu meter`), not from a fixed rotation. |
| `carlecool/library.py` | The library fills slots first (matched by embedding to the slot description). Usage history per clip and series (same producer → `creator_name`). |
| `carlecool/shot_analysis.py` | Add: camera movement vs subject movement (global vs local optical flow, OpenCV `calcOpticalFlowFarneback` at 72×128), motion direction, subject position (saliency), effective resolution (high-frequency energy instead of pixel count), noise / grain level, artefacts (blockiness). Analyse **windows**, not whole clips. Cache by `sha256(file)+window+version`. |
| `carlecool/stylegate.py` | Era and clothing checks as CLIP negatives per director ("modern smartphone", "2020s car") – data in the director file. |

## Phase 3 – Coherence, narrative, cinematography, match cuts

| File | Change |
|---|---|
| `carlecool/coherence.py` | Transitions from **end frame A → start frame B** (embedding + Lab + motion vector of the concrete frames, not clip averages). Continuity of era / vehicle / person (prevent false identity continuity: two different women in the same framing back to back = penalty). |
| `carlecool/coherence.py` → match cuts | Shape (edge / Hough similarity of end and start frames), action (motion impulse on the kick), colour, light, texture, semantic. They count only on musical accents (kick / snare / drop from `analysis.py`). |
| `carlecool/cinematic.py` | Storyboard slots from the plan (function + musical section) instead of `build_storyboard` with hash rotation; beam search assigns clip **windows** to slots. Breaks → visual rest, drop → climax. |
| `carlecool/analysis.py` | Make snare / kick / break / drop markers explicit (librosa onset + band energy). Instruments only as a *probabilistic* hint with a confidence value. **Demucs: not planned** (CPU time 3–6 min / song on the runner, no proven benefit). |
| `carlecool/critic.py` | `plan_score` scores slot fulfilment, musical sync and repeats. |

## Phase 4 – Rendering, colour, critic

| File | Change |
|---|---|
| `carlecool/render.py` | **One** geometric transform per shot (crop + scale + any push combined); grading order: correction (exposure / WB from DNA) → shot matching to the neighbour → creative grade; grain / sharpening / denoise dosed by DNA (noise, sharpness, source); HDR detection (`color_transfer`) → tonemap to SDR BT.709; safe zones for text (top 12 %, bottom 22 % free). |
| Master | **Free full-quality master:** store the master in the Actions cache (`master-<run_id>`) or as an encrypted release asset. The email gets a separate preview. `approve` / `zernio` publish the master after SHA-256 verification. No new costs. |
| `carlecool/critic.py` | Separate **technical errors (objective)** from **aesthetic indicators**. Add: first-2-seconds score, motif clarity (CLIP), stock-video character (CLIP "stock footage / advertisement"), compression artefacts after a simulated platform encode (TikTok ≈ 1080p/≈3 Mbit/s → SSIM against the master), colour continuity at the cuts, A/V sync, true peak after AAC. Targeted rework of single scenes (swap the slot's clip) instead of a whole new edit, **at most 2 rounds**; otherwise mail with a "quality insufficient" note and no publication suggestion. |

## Phase 5 – Learning, comparison tests, resources

| File | Change |
|---|---|
| `carlecool/performance.py` | Fix checkpoints: real `age_hours` always, assignment by age window (d1 = 18–36 h, d2 = 40–60 h, d7 = 6–8 d), relabel or mark invalid the faulty existing entries (D1) – with a migration log. Evaluate new factors (hook strategy, director, theme, coherence, critic, library share, posting time) – **only reported**, nothing adjusted automatically below `MIN_POSTS`. Controlled A/B: stratified by song. |
| `carlecool/decisions.py` | Include `/revise` requests as a signal; calibrate the critic against approve / discard (logistic, only from n ≥ 20). |
| Budgets | Hard limits in one place (`carlecool/budgets.py`): runtime per stage, max downloads, Coverr requests, cache size, CLIP frames. Workflow timeouts derived from them. |
| Validation | `baseline-compare.yml` per phase: identical conditions + an end-to-end run with each pipeline's own search; blind A/B mail; results in `docs/validation.md`. **No claimed improvement without this evidence.** |

## Hard budgets (proposal)

- Runtime: ≤ 45 min per Reel including waiting for Coverr (today ~8–60 min).
- Coverr: ≤ 35 requests per run, ≤ 50 per hour.
- Downloads: ≤ 24 clips per run.
- CLIP: ≤ 8 frames per clip window, ≤ 30 clips.
- Cache: ≤ 3 GB library, ≤ 1 GB masters (7-day eviction).
- No new paid services.
