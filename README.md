# CarleCool — SoundCloud → curated Reels → Gmail review → Instagram

**Implemented:** daily candidate creation, last 20 public SoundCloud tracks, tempo/energy estimate, your 40 curated Urban/Skate/Graffiti/Gen-Z/Retro video search phrases, 3 Coverr queries max, licensed fallback, FFmpeg beat-grid 9:16 montage, GitHub Actions artifacts, Gmail review email with small MP4 attachment, approval issue, and Instagram publishing of the **exact SHA-256-verified** original.

**Never automatically publishes just because a schedule runs or an email link is clicked.** Only the authenticated repository owner can write `/publish` on an open `carlecool-review` issue, and publishing is additionally blocked by `PUBLISH_ENABLED` unless explicitly enabled.

## 1. Make this repository private first

GitHub → **Settings → General → Danger Zone → Change repository visibility → Private**. Workflows intentionally refuse to render your music if the repository is public (Actions artifacts would otherwise be publicly accessible). Never commit music masters, video downloads or access tokens.

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

## 3. Run once in dry-run

GitHub → **Actions → CarleCool — make and review Reel → Run workflow** → choose `dry-run` → Run. This creates a 30-second 1080 × 1920 H.264/AAC MP4 from a current SoundCloud song and up to 8 clips. View **Artifacts** at the bottom of that completed run to download it. Nothing goes to Instagram or Gmail in `dry-run`.

If there are no original tracks, no SoundCloud API credentials, or no stock clips, the run **fails safely** and reports exactly what's missing. It never fabricates a song or posts anything.

## 4. Test Instagram token without publishing

Open **Actions → CarleCool — Instagram connection check → Run workflow**. The check uses only a GET request to `/me/assigned_instagram_accounts` to discover the account assigned to your Unified Login token. It does not upload or publish any Reel. If several Instagram accounts are assigned, set the intended numerical `IG_USER_ID` explicitly. Keep `PUBLISH_ENABLED` absent/false.

The new Meta Unified Login requires a business portfolio, but no Facebook Page. A SUAT is not interchangeable with older tokens; if the check fails, verify the correct token type and the approved Instagram permissions.

## 5. Enable the Gmail review

Once the dry-run is good, run `review` or let the daily scheduled workflow run at 10:15 UTC (11:15 Berlin winter / 12:15 summer, approximate). It creates a GitHub **Issue** labelled `carlecool-review` and sends you a Gmail with:

- Song title, video style / search queries, caption and SoundCloud link.
- A small MP4 attachment if email provider limits permit, plus the original under the issue's workflow-artifact link.
- A link to the approval Issue. Merely opening the link **never publishes**.

To publish **this exact video**, open the Issue in GitHub while signed in and comment **`/publish`**. This triggers `approve-reel.yml`, downloads the original rendered MP4 from the referenced earlier workflow run, verifies its SHA-256 hash and caption and checks licensing and posting journal, then sends it via the official Instagram API. To discard, comment **`/reject`**. The next day can then propose another Reel. Pending issues prevent additional scheduled proposals.

A review artifact expires after 7 days. Publishing an expired artifact fails, it never silently rerenders or substitutes a new video. After a network failure in an ambiguous Instagram publish, the journal remains pending and blocks further posts until manual reconciliation.

**GitHub workflow permissions:** GitHub Actions must have ability to write repository contents for the pending/published journal. Under Settings → Actions → General → Workflow permissions, grant read/write if required. GitHub issue and artifact permissions are scoped in workflows.

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
- `carlecool/keywords.py`, `carlecool/video.py`: your exact 40 keywords, score-based search and licensed stock fallback.
- `carlecool/render.py`: portrait video montage.
- `carlecool/review.py`: Issue and Gmail email proposal; no posting.
- `carlecool/approve.py`, `carlecool/instagram.py`: fixed-asset approval, audit log and Meta publishing.
- `.github/workflows/daily-reel.yml`, `approve-reel.yml`, `test.yml`: workflow orchestration and tests.

## Provider documentation

- [SoundCloud API](https://developers.soundcloud.com/docs/api/guide)
- [Coverr videos API](https://api.coverr.co/docs/videos/)
- [Coverr API key usage](https://coverr.co/api/docs/auth/)
- [Meta Instagram Unified Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/)
