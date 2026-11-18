# TikTok setup for CarleCool (November 2026)

**Status: Not connected.** The approval email offers three destinations, but only Instagram has an implementation. The TikTok and both-platform GitHub commands deliberately fail **before uploading to either platform**. Do not set an arbitrary TikTok secret and assume this enables posting.

## Official registration and audit

1. Visit https://developers.tiktok.com/ and sign in with a TikTok developer account. Under **Manage apps**, select **Connect an app / Create app**.
2. Complete app details (name, category, description, icon), choose **Web** or **Desktop**, and provide a real official website. Provide reachable terms of service and privacy policy pages.
3. In **Products**, add **Login Kit** for creator OAuth and **Content Posting API**. Enable **Direct Post** if public direct publishing is intended. Request the **video.publish** scope. The alternative **video.upload** supports uploads for completion by the artist in TikTok; it is not direct publication.
4. In Login Kit configure a valid HTTPS OAuth redirect URI on a website you actually control. Use https://www.tiktok.com/v2/auth/authorize/ with client_key, scope=video.publish, redirect_uri, response_type=code, state. Exchange the returned one-time authorization code securely server-side via https://open.tiktokapis.com/v2/oauth/token/. Never publish client_secret, access_token or refresh_token in GitHub, an email or issue.
5. TikTok's application form may require verification of website / Terms / Privacy Policy URLs (and Content Posting URL properties). Verify ownership in **URL properties**.
6. Test the flow in **Sandbox** first. TikTok requires the direct-post UI to fetch creator info, show the creator identity, ask for the choice of privacy setting (without a preselected default), allow caption and interaction controls, handle disclosures and explicit final consent. The creator must authorize the app.
7. Submit the app for review with a real end-to-end demonstration video and explanations of its scopes. **Unaudited apps are limited to private visibility.** TikTok's content-sharing guidelines explicitly reject internal or team-only upload utilities, so an app just for the CarleCool account may be denied. Approval is not guaranteed.
8. Only once your particular app and user authorization are approved should a production integration be built: query creator info, show current privacy/interaction permissions to the owner, verify explicit consent, upload the SHA-256-checked original using the officially permitted file/URL method, poll posting status, journal the result and prevent duplicate posts. Multi-platform publishing needs *separate* Instagram/TikTok idempotency and recovery journals.
9. Store all secrets as private GitHub Actions Secrets **only when ready**, with refresh-token rotation implemented. Do not enable posting by a single toggle without tests and license clearance.

**For a tool intended only for one own TikTok account, investigate an established approved publishing service first**, or use TikTok's official upload-to-inbox flow (which still requires authorization and a finishing step inside TikTok).

Official references:
- https://developers.tiktok.com/docs/en/getting-started-create-an-app
- https://developers.tiktok.com/docs/en/login-kit-web
- https://developers.tiktok.com/docs/en/oauth-get-a-user-access-token
- https://developers.tiktok.com/docs/en/content-posting-api-get-started
- https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content
- https://developers.tiktok.com/docs/en/content-sharing-guidelines

## Review email semantics

Choose exactly one owner comment on the new labeled GitHub Issue opened from the email:
- \`/publish instagram\` — existing Instagram-only workflow (still subject to PUBLISH_ENABLED and footage/music licensing).
- \`/publish tiktok\` — reserved, currently blocked. No TikTok call.
- \`/publish both\` — reserved, currently blocked *before Instagram*. No partial single-platform posting.

The email buttons **open GitHub for authenticated confirmation**; they do not post directly. Email-client security scanners may follow hyperlinks, so the final owner-only GitHub comment is mandatory. The old \`/approve\` and \`/publish\` commands remain aliases for Instagram.
