# CarleCool — SoundCloud → curated Reels → Gmail review → Instagram

**Implemented:** daily candidate creation, last 20 public SoundCloud tracks, tempo/energy estimate, 60 curated Urban/Skate/Graffiti/Gen-Z/Analog/Zen video search phrases, 3 Coverr queries max, licensed fallback, FFmpeg beat-grid 9:16 montage, private Gmail email of the exact Reel (no public Actions artifacts), approval issue, and Instagram publishing of the **exact SHA-256-verified** original.

**Never automatically publishes just because a schedule runs or an email link is clicked.** Only the authenticated repository owner can write `/publish` on an open `carlecool-review` issue, and publishing is additionally blocked by `PUBLISH_ENABLED` unless explicitly enabled.

## Video quality v4 — cover-led footage, beat editing, full-quality master (2026-11-19)

What changed and why:

| Area | Before | Now |
| --- | --- | --- |
| Search | 60 phrases collapsed to 7 generic Coverr words (`music`, `sunset`…) | The full art-direction phrase is searched; the broad word is only a fallback (≤ 6 requests) |
| Cover | Only re-ordered 8 already-downloaded clips | The cover **chooses** 2 of 3 search phrases (OpenCLIP, or a warmth/brightness/saturation fallback) and ~24 candidates are **ranked by thumbnail before download**; the best 7 are kept, at least one per lane |
| Look | Same desaturation filter on every clip | Per-clip 3D LUT (Reinhard colour transfer in Lab) towards the cover palette, bounded strength |
| Orientation | Landscape clips centre-cropped to 9:16 | **Portrait first** (API flag *and* real file check). Landscape only fills up when fewer than 4 portrait clips exist and never opens/closes the Reel (Coverr's free catalogue is mostly 16:9). Strict mode: repository variable `CARLECOOL_PORTRAIT_ONLY=true` |
| Music | 8 kHz RMS tempo guess, fixed 8-beat grid, loudest 30 s | librosa beats + bass-onset downbeats, per-beat energy; low energy → 8 beats per shot, peaks → 2 beats; a cut lands on the hook |
| Length / hook | 30 s | **8–15 s, whole bars** (ends on a downbeat → clean loop); excerpt starts one bar before the biggest energy lift, so it hits in the first ~1–3 s. `REEL_SECONDS` is now the maximum (default 15) |
| AI shot | Opened and closed the Reel (weakest clip as hook) | Appended last and never used as first/last shot |
| Encoding | 30 fps, bicubic, CRF 22, 128k AAC, forced 2.5 Mbit/s for Gmail | 24 fps, Lanczos, CRF 18 (`-tune grain`), ≤16 Mbit/s, 256k AAC, two-pass −14 LUFS |

### Free archival footage: NASA and Prelinger (2026-11-21)

- **NASA** (Rubin and Night styles, no key): planets, nebulae, Earth from orbit. Talks, news, trailers and items crediting partner agencies (ESA, JAXA, "courtesy of", ©) are excluded; never shows NASA logos as intent (CLIP rejects spacecraft/logo frames).
- **Prelinger Archives** (Lana style, no key): only **public-domain amateur/home movies** (Kodachrome road trips, towns, summers) — no ads, brands, propaganda or accident films.
- Only a ~9 s segment is cut from the remote film (no full download). Three spots per film are sampled; OpenCLIP must rate the frames as the wanted scene rather than people/interviews, text, logos, spacecraft or black-and-white; after cutting, start/middle/end must pass again. Without OpenCLIP no archive footage is used.
- Max. 2 archive clips per Reel, landscape, never first/last shot. Low-resolution footage (crop upscale > 3×) is shown **framed** (full width over a blurred copy) instead of a mushy 9:16 crop.
- Caption credits "Archive footage: NASA" / "Prelinger Archives, public domain"; the rights check enforces them. Off: `CARLECOOL_ARCHIVES=false`.

### Cover style, cover end card and signature shots (v4.1, 2026-11-21)

Built **on top of** v4 (the reverted Creative v5 replaced the v4 search lanes and looked clearly worse):

- **End card with the artwork:** the last ~2.6 s show the song cover (square, centred) with "carl e cool" + title over a dark scrim. The same frame is the **Instagram and TikTok cover image** (`thumb_offset` / Zernio `thumbOffset` / `video_cover_timestamp_ms`), so the profile grid shows the song covers. Off: variable `CARLECOOL_COVER_ENDCARD=false`.
- **Style from the cover (OpenCLIP):** Lana/Americana (rider, flag, horse, vintage car, motel…), Rick Rubin/Minimal (planet, space, sphere, calm ocean…), Night (dark cover, brightness < 0.24). Unclear covers keep v4 unchanged. A style only nudges: lane weights 50/50 with the profile, a mild extra grade after the cover LUT, Rubin slows cuts only if pace is "medium". Shown in the review mail; one-off override `/revise stil lana|rubin|night|auto`; variable `CARLECOOL_STYLE` (`auto`, a style, or `off`).
- **Signature shots (added, never replacing v4 clips):** a skater (face not visible: feet/wheels/silhouette queries, CLIP "seen from behind", OpenCV rejects large frontal faces), a natural-looking woman (CLIP prefers candid over posed/glamour) and a cover motif echo (horse riding, planet …). Each appears exactly once in an interior shot; at most half of the interior shots, skater and woman first. Clips used in the last 30 previews are never reused for these slots. Off: `CARLECOOL_SIGNATURE=false`.

### Portrait footage from Pexels, song naming and end title card

- **Pexels (portrait 9:16):** live runs showed Coverr returns 0 portrait clips. With the secret `PEXELS_API_KEY` (free key from https://www.pexels.com/api/) Pexels is searched first with `orientation=portrait` (full phrase, then its core words; ≤ 6 requests, limit 200/hour), files closest to 1080×1920 are used, and the caption credits Pexels and each creator. Without the key Coverr remains the source.
- **Song name everywhere:** `carl e cool - <title>` (spelling of the Apple Music/Deezer profile; override with variable `CARLECOOL_ARTIST_NAME`) on Instagram's audio label (`audio_name` / Zernio `audioName`), caption, review mail and approval issue. TikTok has no API field for the sound name.
- **Caption:** first line `🎧 carl e cool - <title>`, then footage credits and hashtags (no track link line).
- **Smart 9:16 crop for landscape clips:** instead of a centre crop (which keeps only the middle ~32 % and often misses the subject), each shot's frames are analysed (motion spread to subject width, plus detail and a mild centre prior) and the 9:16 window is placed on the most interesting area; if the subject moves, the crop pans smoothly (eased, speed-limited). Portrait clips are untouched. Disable with variable `CARLECOOL_SMART_CROP=false`.
- **End title card:** artist + song title fade in over the last ~2.2 s, centred above the platform UI. Disable with variable `CARLECOOL_TITLE_CARD=false`.

### Full-quality master outside Gmail (optional, recommended)

Without configuration the master must still fit a Gmail attachment (≤16 MB; at 8–15 s this is ~8+ Mbit/s, usually fine). For the uncompromised master use a **private** Cloudflare R2 bucket (free tier, 10 GB):

1. Cloudflare → R2 → *Create bucket* (e.g. `carlecool-masters`), keep it **private**, no public URL. Optional lifecycle rule: delete objects after 30 days.
2. R2 → *Manage API tokens* → token with *Object Read & Write* for that bucket only.
3. GitHub → Settings → Secrets and variables → Actions:
   - Secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` = the R2 token's key pair.
   - Variables `MASTER_S3_BUCKET` = bucket name, `S3_ENDPOINT_URL` = `https://<account-id>.r2.cloudflarestorage.com`.

Then the review email carries a 720p preview, the master goes to `carlecool/masters/<run_id>/<sha256>.mp4`, and `/publish` downloads it and verifies the SHA-256 from the approval issue (the review email must still exist in Gmail Sent; deleting it still cancels).

## Creative Intelligence v3 (2026-11-19)

A free, bounded enhancement to the existing *human-reviewed* pipeline:

- **Cover visual semantics:** optional `OpenCLIP ViT-B-32 / laion2b_s34b_b79k` compares the artist's official public SoundCloud cover with up to three sampled frames from each downloaded licensed clip. Descriptive visual themes are inferred from text/image embeddings. Only **public model weights** are downloaded; no private audio or images are uploaded to a model service. The daily workflow attempts OpenCLIP automatically on a standard free GitHub runner; set repository variable `CARLECOOL_SEMANTIC=off` to disable model loading and use the palette-only path. Optional installation/model failures also automatically fall back to palette matching. Only public pretrained weights are cached, never artist media. Model download and CPU inference can be slow/unavailable and are not guaranteed to succeed. Confirm the model's applicable license before commercial deployment.
- **Musical structure:** measures abrupt energy transitions *within the chosen excerpt* and safely snaps existing beat-phase cuts to nearby transitions. This is a heuristic: it does **not** positively identify choruses, exact downbeats or true drops.
- **Narrative edit:** deterministic visual opening/closing motif based on ranked footage; intermediary shots avoid immediate repetition and advance within source videos instead of restarting.
- **Public search-interest signals:** daily email-preview workflow reads Google's public US Trending Now RSS (read-only, strict size/timeouts, 7-day freshness); only a small whitelist of visually relevant terms can influence the third Coverr query. Google searches are **not evidence of Instagram/TikTok virality**. An unavailable or irrelevant feed leaves the normal creative searches unchanged. Local/offline tests have trend fetching disabled.
- **Transparent owner-feedback learning:** successful, authenticated `/revise` style commands update a bounded `data/creative-learning.json` preference vector (+/-8 per lane), persisted alongside the existing public creative profile. This is deterministic online preference adaptation, **not trained engagement prediction**. No personal, audio or media data are stored.
- **Three private editing alternatives:** `python -m carlecool.variant_compare --audio /path/to/owned.mp3 --video /path/to/licensed.mp4 --output /private/output --length 20` produces Americana Cinema, Rubin Minimal and Electronic Cut previews and a `comparison.json` metadata sheet. These are local media: never commit/upload them to the public repository. Human selection is still required. The synthetic FFmpeg CI smoke exercises all three variants.
- **Safe gates unchanged:** owner approval, Coverr license clearance, Gmail original hash checks and Instagram publishing restrictions remain in place. No automatic social publishing.

**Operational costs:** all local computation and public data sources are free-to-use *subject to hosting quotas, third-party terms and API limits*. OpenCLIP may cause large first-time dependency/model downloads and high CPU time; monitor public-runner limits and verify model terms. Set `CARLECOOL_SEMANTIC=off` if the overhead is undesirable.

### Validation

```bash
python -m pytest -q
python scripts/offline_smoke.py
```

The default test pipeline validates the no-network code paths and three **synthetic** video variants. It cannot certify the subjective quality of real reels, external model availability, full Coverr licensing or Instagram engagement. The real CPU pretrained-model smoke workflow independently exercises OpenCLIP on synthetic video. Review the first production preview and the semantic/palette fallback metadata before trusting its artistic ranking.

## Public repository / zero-cost GitHub Actions

Use **public repository + standard Ubuntu runners** so GitHub Actions compute is free. **Never upload media or original audio as GitHub Actions artifacts**, never commit original tracks, and never print secrets to logs. The code now sends the exact hashed MP4 privately as a Gmail attachment and later fetches it from the authenticated sender's **Sent** mailbox using Gmail IMAP upon an owner-only `/publish` issue comment. The public Issue contains song/approval metadata only, not music files. The original stays in the mailbox until approval or deletion. Test with an authorized Gmail App Password; both SMTP and IMAP must work. Gmail attachment size is capped at 16 MB with automatic size reduction by the render step. For `dry-run`, the MP4 is emailed privately without an issue. Deleting the sent email before approval makes publishing fail safely.

**Visibility is an account-level GitHub Setting:** Settings → General → Danger Zone → Change repository visibility → Public, **only after** verifying historical commits, Issues, Actions logs and artifacts have no private data. Change visibility yourself; this script will not disclose media as artifacts. Secrets stay in GitHub Actions, but metadata, code, issue titles and logs are public. No automatic publication until `PUBLISH_ENABLED=true` and Coverr commercial clearance are explicitly provided.

## Free ZeroGPU AI-video experiment — explicitly opt-in only

A prototype for **real 2-second text-to-video** scenes from the official
[Lightricks/LTX-2-3 Space](https://huggingface.co/spaces/Lightricks/LTX-2-3)
is at [carlecool/ai_video.py](carlecool/ai_video.py). It uses the
[Hugging Face ZeroGPU free quota](https://huggingface.co/docs/hub/spaces-api-endpoints),
never paid inference or paid fallback, and sends only a public-safe English
aesthetic prompt. The code first verifies that the Gradio API is reachable and
then requests **exactly one** low-resolution 2-second test clip. The
[isolated live smoke workflow](.github/workflows/free-ai-video-smoke.yml)
does not send an email, create a public video artifact or publish to Instagram.
It explicitly fails if generation does not actually work.

A manually invoked Reel can use `CARLECOOL_AI_VIDEO=one` after installing
`gradio_client`; it will mix at most **one** AI shot with Coverr and fall back
to Coverr upon quota exhaustion or Space errors. **Scheduled daily Reels stay on
Coverr by default** until the real test passes and the artist chooses to enable
experimental AI scenes. For publishing any AI-inclusive Reel, an additional
`AI_VIDEO_PUBLISH_LICENSE_CONFIRMED=true` gate is required on top of the
existing owner and Instagram gates. Generated media are stored only on the
ephemeral runner and sent through the private-review pipeline.

Important limits: Anonymous ZeroGPU requests currently get 2 minutes of
shared GPU time daily; free Hugging Face accounts get 5 minutes (requires a
Hugging Face access token configured as GitHub Secret `HF_TOKEN` to use the
account quota). The remote Space may be paused, queued or unavailable, and its
Gradio API can change without notice. Neither the 2-second trial nor future
daily generation is guaranteed. Model and hosting licenses need to be checked
before commercial publication.

## Creative Control v2 — preset, style feedback, safer review

The default "Rubin / Analog / Lana-Americana / 90s Skate" mix is now a **real configuration** at [data/creative-profile.json](data/creative-profile.json), not just a descriptive prompt. It controls three weighted Coverr searches, shot pacing, desaturation and grain, and optional use of a song's first 30 seconds. See [full presets and supported controls](docs/creative-control.md) and [master visual direction](docs/visual-direction.md).

A **review-mode** email contains the original MP4 and a **direct clickable approval Issue URL**; owner comments `/revise mehr natur, weniger skate`, `/revise more_mpc`, `/revise preset_rubin_lana`, `/revise slower_cuts` or `/revise more_super8` make a *new* private MP4 and a *new* approval Issue. Previous approval is disabled; successful style feedback updates the repository's public, nonsecret creative-profile weights for future Reels. Only owner comments are accepted. Plain-text requests are interpreted with a limited rule set, not generative AI. `/approve` or `/publish` still require separate Instagram enablement and rights clearance.

**Important:** The first old `dry-run` test emails have no approval link because they never created an Issue. For a preview *with a link*, use the `review` mode or the special one-time review test workflow. Opening a review link alone NEVER posts to Instagram.

## CarleCool visual identity

See [docs/visual-direction.md](docs/visual-direction.md) for the master English prompt and the Apple-clean / Malibu-Zen / raw 1990s skate / Y2K digicam / Americana / corecore visual design. The code searches 60 curated phrases using a three-lane stillness/action/nostalgia mix instead of only popular urban footage. Actual AI-generated clips, full creative overlays or image-recognition scoring are not included.

## 1. Repository visibility and safeguards

Keep original music in private legitimate storage. Do not store MP4s in GitHub artifacts or commit credentials. Public GitHub metadata (Issues, commit journal) is not private.

## 2. Set up Secrets and Variables

Go to **Settings → Secrets and variables → Actions**.

**Repository secrets** (never paste these in chat or commit them):

| Name | Purpose |
| --- | --- |
| `COVERR_API_KEY` | Your Coverr Free key |
| `SOUNDCLOUD_CLIENT_ID`, `SOUNDCLOUD_CLIENT_SECRET` | Authorized SoundCloud app credentials (Artist Pro membership alone is not an API key) |
| `GMAIL_ADDRESS` | Sending Gmail address |
| `GMAIL_APP_PASSWORD` | Google app password for Gmail SMTP (requires eligible Google account and 2-step verification; do not use your normal Gmail password) |
| `REVIEW_EMAIL` | Destination Gmail address for the Reel suggestion; can be same address |
| `IG_USER_ID` (optional), `IG_ACCESS_TOKEN` | Instagram account ID (optional with one assigned account), Unified Login system user token |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Only if using private S3/R2 storage for *your own* audio or owned stock clips |
| `PUBLISH_ENABLED` | Only set to `true` after end-to-end preview, rights and Meta checks |
| `COVERR_PUBLISH_PERMISSION_CONFIRMED` | Only set to `true` **after** confirming your actual Free API attribution method with Coverr |

**Repository variables:**

| Name | Purpose |
| --- | --- |
| `SC_ALLOW_OFFICIAL_DOWNLOADS` | `true` only for your own downloadable SoundCloud tracks, if SoundCloud authorizes official downloads |
| `AUDIO_S3_BUCKET` | Your own originals in private S3-compatible storage, named `carlecool/audio/<track_id>.mp3` |
| `AUDIO_S3_PREFIX` | Optional, defaults to `carlecool/audio/` |
| `STOCK_S3_BUCKET` | Optional private licensed-stock backup clips |
| `S3_ENDPOINT_URL` | Optional S3-compatible R2 endpoint |

**Audio is already available** from the artist-published SoundCloud RSS enclosures without manual uploads. This is the publicly distributed podcast encoding, not the lossless original master. No stream ripping is implemented. Coverr Free requires attribution (potentially a clickable logo according to the plan). The included caption credit may **not** satisfy this condition; get express confirmation before enabling publishing.

## Automatic original-song selection from SoundCloud RSS (2026-11-17)

CarleCool's **official public podcast RSS feed has audio enclosures for all 20 of its newest public tracks**, even though direct original-file downloads are disabled. The pipeline now matches the selected SoundCloud numeric track ID to the RSS item's GUID, validates the signed/published `<enclosure>` and HTTPS SoundCloud CDN host, downloads the **artist-published RSS audio** only into the temporary GitHub runner, probes that it is decodable, and removes it with runner cleanup. **No manual MP3 uploads, Mac runtime, GitHub media artifacts or stream-ripping.** Audio is the published podcast-encoded file, not necessarily the lossless original master.

The code defaults to `SC_USE_RSS_AUDIO=true` for the published public RSS feed; you may set repository variable `SC_USE_RSS_AUDIO=false` to disable this route. Do not enable public downloads of original masters for this feature.

A dedicated [RSS audio smoke workflow](.github/workflows/rss-audio-smoke.yml) verifies the **actual downloaded audio** separately from mocked unit tests. Do not enable scheduled Reel production until that workflow and the real Gmail Reel delivery complete successfully. Instagram posting remains approval-only and disabled until rights and credentials are verified.

## Daily automated preview activated

**The SoundCloud RSS audio source has now been tested with a real track:** the latest 20 tracks have public RSS audio enclosures, and a full 9:16 Reel render followed by a private Gmail MP4 attachment succeeded in GitHub Actions (17 November 2026). The previously configured `CARLECOOL_AUDIO_READY` job gate is no longer required.

Every day at **19:30 Europe/Berlin** (CET/CEST, subject to GitHub Actions scheduler delays), GitHub Actions chooses a song at random **among the least-used songs in the latest 20 public SoundCloud releases**. This produces a fair rotation: with a fixed catalog, each song is used once per round of 20 before any song receives its next turn. The pipeline analyzes the official RSS audio, searches Coverr with a new run-specific visual seed, renders a Reel, and sends a private Gmail video plus a new approval Issue. **An older review issue no longer blocks tomorrow's new Reel.** Never automatic Instagram publication.

The nonsecret `data/preview-history.json` journal records only song IDs, Coverr clip IDs, dates, GitHub run IDs and rendered hashes, **after a successful private email**. Revisions count toward recent clip avoidance but not toward daily song frequency. Preview history is separate from the immutable Instagram publishing journal; no MP4, music or email address is committed.

**Publishing remains disabled** until the user has reviewed the video, verified rights to the music/visuals and confirmed requirements for the Coverr free Demo API license. The code now invokes the Coverr download-tracking endpoint after successful footage selection, rejects explicitly premium/watermarked/partner-sponsored results, and credits Coverr plus any creator whose Coverr profile is included in the API response. Verify all selected clips are rights-cleared and the resulting Instagram caption contains the required credits before enabling live publication. See [the Coverr license](https://coverr.co/license). Do not set `PUBLISH_ENABLED=true` just to test. A public GitHub Issue reveals track titles, caption and selection metadata, not the video or SoundCloud credentials.

## SoundCloud artist authorization (new)

SoundCloud OAuth 2.1 (PKCE) supports a separate **read-only owner identity and track-metadata probe**. See [docs/soundcloud-owner-oauth.md](docs/soundcloud-owner-oauth.md) for the one-time Mac sign-in. The local helper encrypts rotating access/refresh tokens into a public-safe ciphertext file; the decryption key remains a GitHub Secret. After setup, a scheduled owner-check keeps credentials refreshed. **Neither that probe nor existing app credentials prove SoundCloud permits automated original-audio download** while public downloads are disabled. No stream ripping is implemented.

The official SoundCloud RSS route is verified with real song audio, so the daily proposal schedule runs without the old audio-ready gate. The OAuth owner probe is **optional and not required** for this already functioning RSS route. Instagram remains independently gated and disabled.

## Free original music without publishing masters on GitHub

SoundCloud streams are transcoded and are **not the original upload**. Direct downloading through SoundCloud requires an officially downloadable track; enabling downloads lets other signed-in listeners obtain that uploaded file too. SoundCloud API Terms also restrict persistent downloads by apps, so do not turn on scraping or automatic stream ripping. The read-only provider check reports the newest public track's numeric SoundCloud ID and how many of the 20 tracks are marked downloadable.

**Preferred free private workflow:** In the same Gmail account already configured in GitHub Secrets, email your own MP3 master **from that address to itself**. Use the exact subject `CARLECOOL_AUDIO_123456789` where `123456789` is the numeric SoundCloud track ID, and attach a file named `123456789.mp3` (or `.wav`, `.flac`, `.m4a`). Do this once for each song (Gmail's normal attachment-size limits apply; our importer currently caps originals at 23 MB). Keep those messages in your Sent mailbox. The workflow looks up the selected song's original privately via authenticated IMAP, validates sender, recipient, subject and filename, and uses it only in-memory/temporary runner storage. It never commits songs or includes them in public artifacts.

For a first trial, send **one** original MP3 of the newest SoundCloud song, then manually start the CarleCool daily Reel workflow in `dry-run` mode. The resulting Reel will be privately emailed to your `REVIEW_EMAIL`. If stock footage is not available or a required right is unresolved, the run stops without publishing anything.

## 3. Run once in dry-run

GitHub → **Actions → CarleCool — make and review Reel → Run workflow** → choose `dry-run` → Run. This creates an 8–15-second (whole bars) 1080 × 1920 H.264/AAC MP4 from a current SoundCloud song and up to 8 clips. The exact rendered MP4 is emailed privately to `REVIEW_EMAIL`. No GitHub artifact is uploaded, no GitHub review Issue is opened, and nothing goes to Instagram in `dry-run`.

If there are no original tracks, no SoundCloud API credentials, or no stock clips, the run **fails safely** and reports exactly what's missing. It never fabricates a song or posts anything.

## 4. Test Instagram token without publishing

Open **Actions → CarleCool — Instagram connection check → Run workflow**. The check uses only a GET request to `/me/assigned_instagram_accounts` to discover the account assigned to your Unified Login token. It does not upload or publish any Reel. If several Instagram accounts are assigned, set the intended numerical `IG_USER_ID` explicitly. Keep `PUBLISH_ENABLED` absent/false.

The new Meta Unified Login requires a business portfolio, but no Facebook Page. A SUAT is not interchangeable with older tokens; if the check fails, verify the correct token type and the approved Instagram permissions.

## 5. Enable the Gmail review

Once the dry-run is good, run `review` or let the daily scheduled workflow run at 10:15 UTC (11:15 Berlin winter / 12:15 summer, approximate). It creates a GitHub **Issue** labelled `carlecool-review` and sends you a Gmail with:

- Song title, video style / search queries, caption and SoundCloud link.
- The **exact original MP4** as a private Gmail attachment (not a GitHub artifact).
- A link to the approval Issue. Merely opening the link **never publishes**.

To publish **this exact video**, open the Issue in GitHub while signed in and comment **`/publish`**. This triggers `approve-reel.yml`, downloads the original rendered MP4 from the sending Gmail account's private Sent mailbox via IMAP, verifies its SHA-256 hash and caption and checks licensing and posting journal, then sends it via the official Instagram API. To discard, comment **`/reject`**. The next day can then propose another Reel. Older pending issues do not prevent daily email proposals; each issue must still be approved individually to publish.

A review depends on the original email remaining in the Gmail Sent mailbox. Publishing after deleting the message fails closed; it never silently rerenders or substitutes a new video. After a network failure in an ambiguous Instagram publish, the journal remains pending and blocks further posts until manual reconciliation.

**GitHub workflow permissions:** GitHub Actions must have ability to write repository contents for the pending/published journal. Under Settings → Actions → General → Workflow permissions, grant read/write if required. No GitHub artifact storage is used by media workflows.

## Important limits

- Local music analysis is heuristic, not sophisticated trained multimodal AI. Cut points follow an estimated 8-beat grid, not guaranteed frame-perfect onsets.
- Coverr's API sort `popular` is footage popularity **on Coverr**, not Instagram trends. Up to 3 queries per Reel; no mass downloading.
- SoundCloud API provides public track metadata; actual Reel audio is the artist-published RSS enclosure. Podcast encoding may differ from the original master.
- Live SoundCloud RSS download, Coverr clip retrieval/download accounting, private Gmail preview delivery and read-only Instagram identity have been verified; Instagram **publishing** remains untested and disabled.
- **Instagram publishing is never enabled by default.** For Instagram professional accounts, set up a Meta app and the required permissions for your professional account; tokens expire and need renewal.
- Email requires a Gmail app password. Google Workspace accounts may disallow app passwords; a Gmail OAuth/API implementation would then be needed.

## Local tests

```bash
python3 -m pip install -r requirements.txt pytest
python3 -m pytest -q
python3 scripts/offline_smoke.py
```

The smoke test synthesizes a tone and visual test pattern, renders a shortened 270 × 480 preview and verifies its metadata. **It never calls real provider APIs.** Requires FFmpeg and FFprobe installed. CI runs these checks on every push.

### Code layout

- `carlecool/soundcloud.py`: latest 20 uploaded public tracks.
- `carlecool/audio.py`, `carlecool/analysis.py`: original-only audio lookup and BPM/energy/mood.
- `carlecool/keywords.py`, `carlecool/video.py`: 60 licensed-stock queries organized into three aesthetic lanes.
- `carlecool/render.py`: portrait video montage.
- `carlecool/review.py`, `carlecool/mailstore.py`: private exact-MP4 Gmail transfer, public metadata-only review Issue; no posting.
- `carlecool/approve.py`, `carlecool/instagram.py`: fixed-asset approval, audit log and Meta publishing.
- `.github/workflows/daily-reel.yml`, `approve-reel.yml`, `test.yml`: workflow orchestration and tests.

## Provider documentation

- [SoundCloud API](https://developers.soundcloud.com/docs/api/guide)
- [Coverr videos API](https://api.coverr.co/docs/videos/)
- [Coverr API key usage](https://coverr.co/api/docs/auth/)
- [Meta Instagram Unified Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/)
