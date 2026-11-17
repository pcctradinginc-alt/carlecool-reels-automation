# CarleCool — SoundCloud Owner OAuth 2.1 (read-only phase)

## Current status

The regular client-credentials token successfully finds the 20 newest CarleCool public tracks, but **0/20 currently expose public downloadable originals**. SoundCloud's documented OAuth 2.1 authorization-code flow with mandatory PKCE lets the **artist** grant user-scoped access; that alone does **not** prove the API permits downloading the original audio when public downloads are off. The SoundCloud 2026 OpenAPI spec documents authenticated track metadata and streaming URLs, but does not document a guaranteed owner's-original download operation. Do not assume a stream URL is an original file.

The new owner-check workflow **only reads `/me`, `/resolve`, `/tracks/{urn}`** and reports whether SoundCloud exposes any official `download_url` metadata. It does not download, cache, rip, upload, copy, or publish audio. The existing daily Reel cannot use owner-only SoundCloud audio until a legally and technically supported original-file endpoint is confirmed.

## One-time connection on your own Mac (no music upload)

1. Register an exact redirect URI in your SoundCloud API application, e.g. `http://localhost:8765/callback` **if SoundCloud accepts this localhost URI**. If not, use an HTTPS redirect URI officially accepted for your app. The bootstrap requires exact matching.
2. On your Mac, install the GitHub CLI (`gh auth login`) and clone this public repository. Use a fresh Python virtual environment, then `pip install -r requirements.txt`.
3. **Locally**, provide `SOUNDCLOUD_CLIENT_ID`, `SOUNDCLOUD_CLIENT_SECRET`, and `SOUNDCLOUD_REDIRECT_URI` to the script via your shell or private environment file, not in ChatGPT and not in Git.
4. From the repository root run `python -m scripts.connect_soundcloud_owner`. Sign in to the actual CarleCool account in the opened browser, approve access, and paste the resulting **full redirected URL into the terminal only**. Never paste OAuth authorization codes or returned URLs into a public issue/chat.
5. When prompted, type `yes` to save the **encryption key in GitHub Secrets** as `SC_OWNER_FERNET_KEY` and push only `data/soundcloud-owner.enc` (ciphertext) on `main`. Your access and refresh tokens are never committed in plaintext.
6. Open **GitHub Actions → CarleCool — SoundCloud owner OAuth check (read-only) → Run workflow**. The job checks that `/me` is the CarleCool profile and inspects a maximum of five newest tracks. It produces no posts and sends no email.

### Unattended token renewal

SoundCloud access tokens last approximately an hour and its refresh tokens are **single-use**. The owner-check workflow refreshes only when needed, **encrypts and commits the replacement refresh token before any later API call**. For continuous daily execution, the eventual audio-enabled workflow must share the same token-rotation lock and have permission to update `data/soundcloud-owner.enc`. A failed GitHub push after a refresh can leave a consumed refresh token: fail closed and reconnect manually; do not retry the old token indefinitely.

**Public repo security:** Only the ciphertext is public. The Fernet key is available to trusted main-branch workflows as a GitHub Secret. Treat changes to the workflow/code as security-sensitive; avoid running unreviewed pull-request code with secrets. If access should be revoked, revoke the app in SoundCloud and remove the secret and encrypted file.

## What would unlock fully automatic audio

We need a positively confirmed **official, authorized way to obtain your own track audio** for derivative Reel creation, without exposing public downloads or relying on a stream-ripper. This has not yet been demonstrated. SoundCloud's API Terms restrict caching/downloading user content, so permissions must be checked for this intended reuse. If the connected owner account has no official download capability, the reliable free alternative is an authorized source of owned masters (Mac/NAS sync, private storage, or manually enabled RSS/podcast distribution). None of these options requires daily manual uploads once configured.

References:
- [SoundCloud API Guide / OAuth 2.1](https://developers.soundcloud.com/docs/api/guide)
- [SoundCloud OpenAPI](https://developers.soundcloud.com/docs/api/explorer/api.json)
- [SoundCloud API Terms](https://developers.soundcloud.com/docs/api/terms-of-use)
