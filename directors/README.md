# Creative Directors

Each file here is one Creative Director: everything that makes its Reels.

| Field | What it steers |
|---|---|
| `label`, `summary` | Name in the review mail / log, short description |
| `active`, `order` | Takes part in the rotation (overridden by the repo variable `CARLECOOL_DIRECTORS`, e.g. `lana,night`) |
| `world`, `variant` | Shared base (reference images, cover detection); `variant: "night"` turns on the night checks (no daylight clips, night grade) |
| `references` | Reference image profile in `data/style-refs/<name>.json` |
| `pace` | Cut pace when the owner left it at "medium" |
| `themes` | One theme per Reel: Coverr search `words` (≤ 2 words), signature `roles`, max. `archive` films, text `lines`, `music` profile |
| `search` | Fallback search words without a theme |
| `roles` | Search words per signature role (woman, friends, flag, car, …) |
| `wanted` | Image descriptions the style gate looks for (CLIP) |
| `look` | Editing language: dissolves, slow motion, light leaks, B/W share of Reels, chromatic aberration, step-printing, … |
| `grade` | FFmpeg colour grade after the cover LUT |
| `weights` | Search-lane weights |
| `fx` | Reach effects: opening push, camera drift, flash cuts |
| `hook_lines` | Fallback text lines |

**New director:** copy `lana.json`, change `name` and the fields, commit. Start a test run with
style = the new name. Add it to the rotation with `"active": true` or the variable `CARLECOOL_DIRECTORS`.

Global rules stay in code and apply to every director: no AI clips, women only, no couples,
no nudity, no brand logos, the owner's clip blocklist (`data/blocked-clips.json`), US flag and
classic car in every Reel.
