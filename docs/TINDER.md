# OpenDate-based Tinder connection

The user's later instruction explicitly replaced the original Tinder exclusion and requested **automatic sending on**. The application now implements an unofficial Tinder messaging connector adapted from OpenDate revision `ba179f23b14a416ef9514e579cab6f7431e3ec1c`. Attribution and MIT notice are in THIRD_PARTY_NOTICES.md and licenses/OpenDate-MIT.txt.

This is a working implemented connector with offline contract/integration tests. **No live Tinder account was connected during development:** no session credential was supplied. Upstream endpoint compatibility remains unverified against a live account. Tinder's documented restrictions still apply; this is not an official integration or a claim of platform authorization. Account restrictions and upstream API breakage remain possible.

## Connect your account

1. Copy `.env.example` to `.env` if needed. Configure on your local server:

   ```dotenv
   TINDER_ENABLED=true
   TINDER_AUTH_TOKEN=your_own_account_session_credential
   # Optional expected account ID; otherwise the connection binds to /profile's verified ID.
   TINDER_OWNER_ID=
   TINDER_POLL_INTERVAL=180
   LLM_PROVIDER=anthropic
   ANTHROPIC_API_KEY=your_anthropic_key
   ```

   Keep real values local or in Render's secret environment settings. A Tinder session credential grants account access; never paste it into chat, a ticket or a repository. This application does not collect login passwords, extract tokens from browsers or implement session renewal.

   OpenDate documents obtaining the credential from **your own** authenticated Tinder web session: sign in at `https://tinder.com` on a computer, open browser developer tools → **Network**, refresh/open your inbox, inspect a request to the exact host `api.gotinder.com`, and find **Headers → Request Headers → X-Auth-Token** (header names may be lowercase). Copy only its value into `TINDER_AUTH_TOKEN` in your private environment settings. Do not export/share a HAR, copy a whole request containing cookies, install token-finder extensions or paste scripts into the browser console. If the header is absent or access is blocked, stop rather than bypass login or account controls.

   Source: [OpenDate connector documentation](https://github.com/sumitaich1998/OpenDate/blob/ba179f23b14a416ef9514e579cab6f7431e3ec1c/docs/connectors.md#getting-an-x-auth-token). This is an unofficial session credential, not an official developer API key. [Tinder's terms](https://policies.tinder.com/terms/intl/en/) restrict unapproved API/AI access. Possession of your session token does not establish platform authorization. No credential is obtained or tested by providing these instructions.

2. Restart the application (`./run.sh`, or recreate the Compose service after editing its environment). Sign into the dashboard and open **Settings → Tinder · OpenDate connection**.
3. Confirm account ownership and acknowledge the unofficial connection, then choose **Connect Tinder · automatic replies**. The backend verifies `/profile` and one bounded inbox page before binding the connection to that account and enables automatic sending for this Tinder account while leaving Telegram’s mode unchanged. There is **no per-message approval** while this account’s automatic replies are enabled. Global pause and simulation mode still block live sends.
4. The worker discovers matches and histories on its next poll. In each intended conversation, open **Automation permissions** and enable the owner grant after recording participant consent and AI disclosure. This is a one-time conversation permission, not an approval for each response. Threads without those grants are ingested but do not transmit their content to the reply model or send messages.
5. Automatic replies run in the background on eligible incoming turns. Provide verified personal facts and writing preferences in Settings. Missing model/personal knowledge causes abstention rather than a made-up reply. The application sends no autonomous follow-up when the latest message is yours. First messages are written only when the owner starts a campaign or asks for one in a conversation (see README, *Automatyzuj*).

Global **Pause agent**, per-thread pause/archive and connection **Revoke** immediately prevent new dispatches after the next permission check. Requests already dispatched cannot be recalled. Connecting Tinder never enables Telegram autonomy. Use the separate **Turn off/on Tinder automatic replies** control to choose supervised or automatic Tinder execution; it defaults to on when connecting. Existing thread grants remain required.

## Implemented behavior

- HTTP connector for existing matches, thread messages, verified self identity and message sending. No recommendations, likes or passes are added. First messages go only to existing matches the owner selected, paced and budgeted (see README, *Automatyzuj*).
- Namespaced owner/match/message IDs, complete pagination checks, source-order normalization, strict sender identity, edited/history reconciliation and unknown availability when matches disappear.
- Default 180-second discovery polling (minimum 60 seconds), backing off to 900 seconds when idle. The private interface has no verified supported webhook. Before an actual send the adapter refreshes identity/history again; this adds reads beyond periodic discovery.
- Read-only network/server failures have up to three attempts with short bounded backoff. Rate limits honor Retry-After by suspending requests. Access denial disables the connection; no CAPTCHA or restriction bypass occurs.
- **Message POSTs execute once.** No retries on timeouts, 5xx responses, malformed receipts or ambiguous responses.
- A concrete returned message ID is persisted, then confirmed in fetched thread history with exact outgoing text and sender identity. An ID already present before dispatch is rejected. Unexpected response shapes never synthesize success.
- If a concrete receipt is known but not yet visible, future reconciliation can verify that exact ID. Without a receipt, similar text is insufficient proof and the thread stays blocked. No blind resend is offered.
- The account token stays in the process environment. The database stores only a fingerprint to bind a connection to its configured credential. Token replacement requires an explicit reconnect; another account cannot silently inherit thread state.
- Session expiry disables access. Replace the local credential, restart and reconnect explicitly. Locally revoked thread grants are not automatically restored.

## Validation and limits

Tinder contract/application tests use `httpx.MockTransport`; API calls are not live platform evidence. They cover automatic sends without approval, pagination/read retries, rate limits, stale drafts, revocation during refresh, missing/duplicate/old receipts, timeouts after commit, delayed visibility, identity/token changes, unsupported media, vanished matches, deletion/tombstones and token redaction. The existing three real Chromium tests still target the fictional platform only.

The adapter can validate only documented-in-upstream shapes it recognizes. Unknown sender IDs, missing message IDs/timestamps, unsupported content or incomplete history fail closed. More than 20 pages in a message history requires attention; a capped match listing never implies absent matches were deleted. An incoming message can still arrive after the final refresh and before dispatch: the external service provides no atomic compare-and-send guarantee. Do not infer platform permission or real-life conversational success from these tests.

See reports/VALIDATION.md for the executed result and docs/KNOWN_LIMITATIONS.md for remaining live/service evaluation work.

## Conservative account traffic controls

See [ACCOUNT_RISK.md](ACCOUNT_RISK.md) for the researched rationale, defaults and measured request reduction. The worker caches inactive histories, honors full Retry-After waits (including HTTP dates), limits requests/sends, throttles uncertain-receipt reconciliation, and pauses on restriction/verification or repeated failure signals. A paused worker makes no background Tinder requests. These are service-load/account-safety controls, not a claim of invisibility or a verified safe bot rate. They can delay discovery/replies; after idle backoff, a new incoming message may wait up to the next scheduled poll.

## HTTP 401 after a successful profile check

Tinder can accept an identity/profile request but deny inbox or conversation access. This is an upstream authorization failure, not proof that a token is merely expired. Connect now checks one inbox page before recording/enabling a connection; a 401 is reported as `inbox_access_denied` and the connection remains paused. Existing data and grants are not silently restored. This adds one read-only inbox request to an explicit connect attempt.

Open Tinder's own inbox and complete any account/session checks there. If it works, use the current X-Auth-Token from your own inbox request, update only the private Render variable, redeploy and reconnect explicitly. If access is still refused, stop: this unofficial connector cannot confer permissions or establish platform compatibility. Do not change network identity or disguise the client to bypass an authorization refusal. No conversation-discovery or sending success is inferred from a profile response.
