# CarleCool — SoundCloud → curated Reels → Gmail review → Instagram

**Implemented:** daily candidate creation, last 20 public SoundCloud tracks, tempo/energy estimate, 60 curated Urban/Skate/Graffiti/Gen-Z/Analog/Zen video search phrases, 3 Coverr queries max, licensed fallback, FFmpeg beat-grid 9:16 montage, private Gmail email of the exact Reel (no public Actions artifacts), approval issue, and Instagram publishing of the **exact SHA-256-verified** original.

**Never automatically publishes just because a schedule runs or an email link is clicked.** Only the authenticated repository owner can write `/publish` on an open `carlecool-review` issue, and publishing is additionally blocked by `PUBLISH_ENABLED` unless explicitly enabled.

## Public repository / zero-cost GitHub Actions

Use **public repository + standard Ubuntu runners** so GitHub Actions compute is free. **Never upload media or original audio as GitHub Actions artifacts**, never commit original tracks, and never print secrets to logs. The code now sends the exact hashed MP4 privately as a Gmail attachment and later fetches it from the authenticated sender's **Sent** mailbox using Gmail IMAP upon an owner-only `/publish` issue comment. The public Issue contains song/approval metadata only, not music files. The original stays in the mailbox until approval or deletion. Test with an authorized Gmail App Password; both SMTP and IMAP must work. Gmail attachment size is capped at 16 MB with automatic size reduction by the render step. For `dry-run`, the MP4 is emailed privately without an issue. Deleting the sent email before approval makes publishing fail safely.

**Visibility is an account-level GitHub Setting:** Settings → General → Danger Zone → Change repository visibility → Public, **only after** verifying historical commits, Issues, Actions logs and artifacts have no private data. Change visibility yourself; this script will not disclose media as artifacts. Secrets stay in GitHub Actions, but metadata, code, issue titles and logs are public. No automatic publication until `PUBLISH_ENABLED=true` and Coverr commercial clearance are explicitly provided.

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

**You still need original music files for rendering.** SoundCloud Pro access is *not* a blanket license or technical ability to rip the stream as MP3. Use a legitimate official downloadable track or upload your own masters to a private storage bucket. Coverr Free requires attribution (potentially a clickable logo according to the plan). The included caption credit may **not** satisfy this condition; get express confirmation before enabling publishing.

## Automatic original-song selection from SoundCloud RSS (2026-11-17)

CarleCool's **official public podcast RSS feed has audio enclosures for all 20 of its newest public tracks**, even though direct original-file downloads are disabled. The pipeline now matches the selected SoundCloud numeric track ID to the RSS item's GUID, validates the signed/published `<enclosure>` and HTTPS SoundCloud CDN host, downloads the **artist-published RSS audio** only into the temporary GitHub runner, probes that it is decodable, and removes it with runner cleanup. **No manual MP3 uploads, Mac runtime, GitHub media artifacts or stream-ripping.** Audio is the published podcast-encoded file, not necessarily the lossless original master.

The code defaults to `SC_USE_RSS_AUDIO=true` for the published public RSS feed; you may set repository variable `SC_USE_RSS_AUDIO=false` to disable this route. Do not enable public downloads of original masters for this feature.

A dedicated [RSS audio smoke workflow](.github/workflows/rss-audio-smoke.yml) verifies the **actual downloaded audio** separately from mocked unit tests. Do not enable scheduled Reel production until that workflow and the real Gmail Reel delivery complete successfully. Instagram posting remains approval-only and disabled until rights and credentials are verified.

## Daily automated preview activated

**The SoundCloud RSS audio source has now been tested with a real track:** the latest 20 tracks have public RSS audio enclosures, and a full 9:16 Reel render followed by a private Gmail MP4 attachment succeeded in GitHub Actions (17 November 2026). The previously configured `CARLECOOL_AUDIO_READY` job gate is no longer required.

Every day at **10:15 UTC** GitHub Actions selects an eligible track, retrieves its audio from the artist-published RSS feed, analyzes the segment, searches Coverr, renders a Reel and creates an approval Issue plus a private preview email. **Never automatic Instagram publication.** If a review Issue is still open, it does not generate another Reel; you must approve or reject the previous one.

**Publishing remains disabled** until the user has reviewed the video, verified rights to the music/visuals and confirmed requirements for the Coverr free Demo API license. The code now invokes the Coverr download-tracking endpoint after successful footage selection, rejects explicitly premium/watermarked/partner-sponsored results, and credits Coverr plus any creator whose Coverr profile is included in the API response. Verify all selected clips are rights-cleared and the resulting Instagram caption contains the required credits before enabling live publication. See [the Coverr license](https://coverr.co/license). Do not set `PUBLISH_ENABLED=true` just to test. A public GitHub Issue reveals track titles, caption and selection metadata, not the video or SoundCloud credentials.

## SoundCloud artist authorization (new)

SoundCloud OAuth 2.1 (PKCE) supports a separate **read-only owner identity and track-metadata probe**. See [docs/soundcloud-owner-oauth.md](docs/soundcloud-owner-oauth.md) for the one-time Mac sign-in. The local helper encrypts rotating access/refresh tokens into a public-safe ciphertext file; the decryption key remains a GitHub Secret. After setup, a scheduled owner-check keeps credentials refreshed. **Neither that probe nor existing app credentials prove SoundCloud permits automated original-audio download** while public downloads are disabled. No stream ripping is implemented.

To prevent repeated failing scheduled Reels before the original audio source is established, the 10:15 UTC Reel schedule is gated by repository variable `CARLECOOL_AUDIO_READY=true`. This flag is intentionally **not enabled by the owner OAuth setup**. Manual `dry-run` diagnostics are still available. The Instagram publish gate remains unchanged.

## Free original music without publishing masters on GitHub

SoundCloud streams are transcoded and are **not the original upload**. Direct downloading through SoundCloud requires an officially downloadable track; enabling downloads lets other signed-in listeners obtain that uploaded file too. SoundCloud API Terms also restrict persistent downloads by apps, so do not turn on scraping or automatic stream ripping. The read-only provider check reports the newest public track's numeric SoundCloud ID and how many of the 20 tracks are marked downloadable.

**Preferred free private workflow:** In the same Gmail account already configured in GitHub Secrets, email your own MP3 master **from that address to itself**. Use the exact subject `CARLECOOL_AUDIO_123456789` where `123456789` is the numeric SoundCloud track ID, and attach a file named `123456789.mp3` (or `.wav`, `.flac`, `.m4a`). Do this once for each song (Gmail's normal attachment-size limits apply; our importer currently caps originals at 23 MB). Keep those messages in your Sent mailbox. The workflow looks up the selected song's original privately via authenticated IMAP, validates sender, recipient, subject and filename, and uses it only in-memory/temporary runner storage. It never commits songs or includes them in public artifacts.

For a first trial, send **one** original MP3 of the newest SoundCloud song, then manually start the CarleCool daily Reel workflow in `dry-run` mode. The resulting Reel will be privately emailed to your `REVIEW_EMAIL`. If stock footage is not available or a required right is unresolved, the run stops without publishing anything.

## 3. Run once in dry-run

GitHub → **Actions → CarleCool — make and review Reel → Run workflow** → choose `dry-run` → Run. This creates a 30-second 1080 × 1920 H.264/AAC MP4 from a current SoundCloud song and up to 8 clips. The exact rendered MP4 is emailed privately to `REVIEW_EMAIL`. No GitHub artifact is uploaded, no GitHub review Issue is opened, and nothing goes to Instagram in `dry-run`.

If there are no original tracks, no SoundCloud API credentials, or no stock clips, the run **fails safely** and reports exactly what's missing. It never fabricates a song or posts anything.

## 4. Test Instagram token without publishing

Open **Actions → CarleCool — Instagram connection check → Run workflow**. The check uses only a GET request to `/me/assigned_instagram_accounts` to discover the account assigned to your Unified Login token. It does not upload or publish any Reel. If several Instagram accounts are assigned, set the intended numerical `IG_USER_ID` explicitly. Keep `PUBLISH_ENABLED` absent/false.

The new Meta Unified Login requires a business portfolio, but no Facebook Page. A SUAT is not interchangeable with older tokens; if the check fails, verify the correct token type and the approved Instagram permissions.

## 5. Enable the Gmail review

Once the dry-run is good, run `review` or let the daily scheduled workflow run at 10:15 UTC (11:15 Berlin winter / 12:15 summer, approximate). It creates a GitHub **Issue** labelled `carlecool-review` and sends you a Gmail with:

- Song title, video style / search queries, caption and SoundCloud link.
- The **exact original MP4** as a private Gmail attachment (not a GitHub artifact).
- A link to the approval Issue. Merely opening the link **never publishes**.

To publish **this exact video**, open the Issue in GitHub while signed in and comment **`/publish`**. This triggers `approve-reel.yml`, downloads the original rendered MP4 from the sending Gmail account's private Sent mailbox via IMAP, verifies its SHA-256 hash and caption and checks licensing and posting journal, then sends it via the official Instagram API. To discard, comment **`/reject`**. The next day can then propose another Reel. Pending issues prevent additional scheduled proposals.

A review depends on the original email remaining in the Gmail Sent mailbox. Publishing after deleting the message fails closed; it never silently rerenders or substitutes a new video. After a network failure in an ambiguous Instagram publish, the journal remains pending and blocks further posts until manual reconciliation.

**GitHub workflow permissions:** GitHub Actions must have ability to write repository contents for the pending/published journal. Under Settings → Actions → General → Workflow permissions, grant read/write if required. No GitHub artifact storage is used by media workflows.

## Important limits

- Local music analysis is heuristic, not sophisticated trained multimodal AI. Cut points follow an estimated 8-beat grid, not guaranteed frame-perfect onsets.
- Coverr's API sort `popular` is footage popularity **on Coverr**, not Instagram trends. Up to 3 queries per Reel; no mass downloading.
- SoundCloud API gives current public track metadata. Only original audio you own and can lawfully download is used.
- No live Coverr, SoundCloud, Gmail or Meta integration has been verified until you configure credentials and successfully run the workflows.
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
