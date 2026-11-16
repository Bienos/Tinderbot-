# Account risk and conservative traffic controls — 2026-11-15

## What the research supports

Tinder's official terms restrict unauthorized third-party automation/API interaction and manipulating identifiers to disguise request origins. The official banned-account guidance directs account owners to platform support/appeal processes. The sources inspected provide no public safe request rate for an unofficial messaging agent and no evidence that any particular configuration prevents account restrictions.

Consequently this update reduces unnecessary activity and stops on restriction signals. It does not claim to make the agent undetectable, establish platform authorization or lower a measured ban probability. The truthful client identification, single-account binding, consent/disclosure requirements and existing security boundaries remain.

Primary sources were fetched directly; URLs, access outcomes and hashes are in `reports/account_risk_sources.json`. HTTP 429 semantics and Retry-After parsing follow RFC 6585 and RFC 9110. The Help Center search results about Tinder's own automated features do not establish approval for third-party automation.

## Applied changes

| Control | Current behavior and tradeoff |
|---|---|
| Fewer background requests | Base polling is 180 seconds (minimum 60). Unchanged polls progressively back off to a configurable 900-second idle interval. New-message discovery can therefore wait up to 15 minutes at the default idle cap. A verified send resets idle backoff. |
| Inactive-history caching | Newly discovered threads are read once. Ungranted inactive threads reuse their local snapshot for up to 3600 seconds unless source activity metadata changes. Granted active conversations refresh on scheduled polls even if metadata is absent/unreliable. Sending always performs current identity/history checks; cached inactivity never authorizes a send. |
| Paused means quiet | A global pause stops background Tinder polling. Paused/archived threads skip periodic history reads. The owner can still perform explicitly requested setup/review actions. |
| Reuse verified observations | After a send is verified by exact provider ID/body/sender, local state uses that observed snapshot. The extra post-send profile/history fetch was removed. Strict pre-send refresh and read-back verification remain. |
| Durable request budgets | Defaults: 30 requests/minute and 300/hour across the installation's Tinder connector. Every real request attempt, including GET retries, counts. Recreating the client does not reset these counters. Exhaustion defers requests; it never selects another identity or connection to avoid the limit. |
| Additional send budgets | Defaults: 10 automated sends/thread/hour, 20 across Tinder/hour and 100 across Tinder/rolling day. Existing installation-wide safety caps also apply. These are application choices, not verified platform thresholds or simulated human timing. |
| Server cooldowns | Retry-After accepts delta seconds and HTTP dates. Long valid waits are preserved instead of the previous one-hour clamp. Unrepresentable/extreme values trigger review. A reconnect attempt cannot shorten an active cooldown. Server 503 waits are also honored; a POST 503 remains uncertain and is never retried. |
| Repeated throttling | Server 429 signals get a growing minimum cooldown; three within a rolling day pause the connection for owner review. Checking an already active cooldown does not count as another server event. Local budget exhaustion is distinguished from server throttling. |
| Restriction/verification stop | Access restrictions, locked/legal-denial statuses, verification challenge HTML/explicit top-level markers and unexpected redirects pause access. The system does not attempt the verification challenge or automatically restore the account. Owner attention appears in the dashboard and activity log. |
| Failure circuit breaker | Three consecutive unsuccessful synchronization attempts open the circuit and pause the connection. A complete successful synchronization resets the ordinary failure count. |
| Quiet uncertainty recovery | A concrete but unobserved receipt is checked at most once per poll interval. A missing receipt is never inferred from similar text, and message POSTs still execute once. |

## Pacing of reads (what a large inbox needs)

Found on an account with 470 matches (73 with messages): every thread became due for its hourly refresh at the same moment, 470 requests
against a budget of 300 an hour, so a synchronization never finished and the connection sat in a "local request budget" pause while sending
competed for the same budget. Now: (1) reads never use the last `TINDER_SEND_RESERVE` (default 40) requests of the hour, so sending always
has room; (2) running out of read budget ends the round calmly (no error, no block, `last_sync` moves) and the threads still due are read in the
next rounds; (3) conversations with messages are read first; (4) a match with no messages is refreshed every `TINDER_EMPTY_THREAD_REFRESH`
seconds (default 6 h) unless Tinder's activity metadata reports a change; (5) a conversation that could not be read is retried after
`TINDER_FAILED_THREAD_RETRY` (default 1 h). The bot's health report shows the progress (`threads_read/total`, requests in the last
minute and hour, `import_done`, waiting times) so a stuck synchronization can be diagnosed from the control service (`/admin/fleet`).

## Campaigns (first messages)

Writing first to many new matches is more visible to a platform than answering people who wrote to you, and the sources above give no safe volume for it. Automatyzuj therefore adds its own conservative limits on top of the send budgets above, as three pace profiles chosen per run: *Ostrożny* (one opener every 8 minutes, at most 8 a day, 18:00–22:00 local time), *Zrównoważony*, the default (every 5 minutes, 15 a day, 17:00–22:30) and *Szybki* (every 3 minutes, 30 a day, 10:00–23:00). Spacing is a fixed interval, not simulated human timing. The last `CAMPAIGN_REPLY_RESERVE` sends of the hourly Tinder budget (default 5) and of the daily budget stay free for replies. Openers are never sent outside the window, so nothing goes out at night; replies to people who wrote are not limited by it. `CAMPAIGN_GAP_SECONDS`, `CAMPAIGN_OPENERS_PER_DAY` and `CAMPAIGN_WINDOW` override every profile for the whole installation. Drafts for the owner's own click are not spaced because nothing is sent. Pause, revocation, a rejected or uncertain delivery and restriction signals stop openers like any other send. These numbers are not verified thresholds; fewer and slower is safer, and a platform-approved channel remains the only way to remove the authorization risk.

## Defaults and configuration

The values are listed in `.env.example`. An existing `.env` is not overwritten; change its values deliberately if adopting this profile. The owner can inspect `next_poll`, `blocked_until`, error/review state and recent activity in the dashboard. Automatic Tinder replies remain on by default for a connected, consented/disclosed account, with the existing on/off, global pause and revoke controls.

No official safe-rate evidence was found. Raising limits cannot be represented as safe, and lowering them cannot guarantee the account remains accepted. The most reliable way to remove the authorization risk is a platform-approved integration or a supported channel. This code continues to be unofficial and live-unverified without credentials.

## Measured local effects

`scripts/benchmark_tinder_traffic.py` compares the current code with the previously delivered security-hardened source archive using `httpx.MockTransport`, two fictional matches, five unchanged polls and one actually executed/verified mocked send. No real Tinder account or message is involved.

| Metric | Previous code | Current code |
|---|---:|---:|
| Initial connect + first synchronization | 5 requests | 5 requests |
| Five unchanged polls, two ungranted threads | 20 requests | 10 requests |
| One generated, dispatched and read-back-verified send | 8 requests | 6 requests |
| Message POSTs for the send | 1 | 1 |
| Verified sends | 1 | 1 |

That is **50% fewer unchanged-poll requests** and **25% fewer requests per verified send** in this fixture. Idle backoff further reduces polling frequency, but that additional time-based effect is not included in these request-count percentages. The benchmark bypasses only the configured test request cap so it can finish immediately; it does not bypass production cooldowns or permissions. Full output is `reports/account_traffic_benchmark.json`.

These measurements cannot establish real account acceptance, real traffic characteristics or a detection/ban success rate. Larger or active inboxes will produce different request counts.

## Tests and remaining limits

New tests cover durable request limits, long/date-form Retry-After, reconnect cooldown preservation, restriction and verification stops, repeated failure/throttling pauses, cache refresh on activity changes, paused traffic, reduced repeated reads, deferred receipt reconciliation, server-error POST ambiguity and Tinder send budgets. Existing stale-draft, exact-ID receipt, consent, authentication, isolation and real Chromium simulator tests remain.

No live Tinder operation, detection experiment, account warming test or ban-rate experiment was performed. The tests do not justify a claim that the agent is “less findable.” They demonstrate fewer requests, preserved messaging safeguards and immediate deference to restriction signals. Resolve account issues using the official platform interface/support before explicitly reconnecting.

## Sources

- https://policies.tinder.com/terms/intl/en/
- https://www.help.tinder.com/hc/en-us/articles/360009042331-My-account-is-banned
- https://www.rfc-editor.org/rfc/rfc6585.html#section-4
- https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after
