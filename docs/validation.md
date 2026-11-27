# Validation log (owner brief §17)

No improvement is claimed without evidence. Every comparison is listed with its conditions and its result.

## 1 · Baseline, identical conditions – 27 Nov 2026 (run 46045850445)

- **Conditions:** song "see clear", 18 s, director Lana. Frozen pool of 6 public-domain archive clips. Old = `6c75a7c`, new = `dev/cinematic-system` (packages A–D).
- **Measured:** technically identical (duration, scenes, loudness −14.1 LUFS, true peak −3.7 dBTP). Coherence 0.550 → 0.567 and critic 0.920 → 0.927; both differences are within the noise of a 6-clip pool.
- **Blind owner rating:** **B preferred.** Key: A = new, B = **old**.
- **Conclusion:** on archive-only material, the new pipeline is **not better, rather worse**. The measured scores did not predict the owner's verdict, so the critic and coherence are **not calibrated** yet.

## 2 · Owner's favourite so far – issue #73 ("sleepwell", 27 Nov)

The owner named this Reel the best so far. It was made with the code before the directors and packages A–D, with the Hamptons theme of the video guide.

Facts:
- Lana, theme "Old Money Hamptons", **15.6 s**.
- Text line "pov: the last warm evening of the year".
- Shown clips: a lighthouse, a POV of a hand, golden dunes, a woman holding grass, a woman with her dog. That is calm, natural coastal light, women outdoors, one theme, few motifs.
- The 2 archive films were downloaded but not shown.

This Reel is the reference that the next versions are measured against.

## 3 · New pipeline vs reference #73 – 27 Nov 2026 (issue #82, run 46062134646)

- **Conditions:** Lana, Hamptons theme restored exactly as in #73, short length. Pipeline on main with packages A–D and the National Archives source. Song "see clear", so not the same song as #73.
- **Machine verdict:** critic 0.748, "incoherent" (coherence 0.436). One re-edit did not help.
- **Owner verdict:** **worse than #73.**
- **Causes found:** an off-brief archive home movie (snow, children; now blocked), a song that only half fits the theme (music fit 0.5), only 5 scenes used.
- **Conclusion:** two owner verdicts in a row favour the old pipeline (blind test B = old, and #73). There is no evidence yet that packages A–D improve the films.

## 4 · Phases 2–5 implemented (dev branch, 27 Nov) – not yet validated

Built on the #73 state, as the owner chose. The cinematic pipeline (`CARLECOOL_PIPELINE=cinematic`) contains everything below. Production stays on `classic` until a blind comparison shows a benefit.

- **Phase 2:**
  - Shot DNA v2: camera vs subject motion, direction, noise, blockiness, subject position, edge frames, HDR.
  - DNA cache keyed by file hash and version.
  - Era negatives per director.
  - Plan-led search.
  - Series bonus in the library.
- **Phase 3:**
  - Transitions measured on the real cut frames.
  - Nine dramaturgic slot functions taken from the music.
  - Function fit and match cuts on musical accents.
- **Phase 4:**
  - Free full-quality master in the Actions cache, with a verified preview fallback.
  - One transform for punch-in plus zoom.
  - HDR tone mapping.
  - Safe zones for text.
  - Critic split into technical and aesthetic parts (true peak, A/V length, simulated platform SSIM, opening, colour at cuts), with at most 2 re-edits.
- **Phase 5:**
  - Checkpoint fix with a migration log; only same-age snapshots are compared.
  - Factor report (pipeline, director, theme, hook) as report only.
  - Revision requests as a signal.
  - Critic calibration from n ≥ 20 verdicts.
  - Central budgets.

**Evidence of better quality: none yet.** It can only come from blind comparisons against #73 and the owner's verdicts.
