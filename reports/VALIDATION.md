# Current validation — compressed Tinder responses and safe diagnostics, 2026-11-15

## Executed suite

`PLAYWRIGHT_BROWSERS_PATH=/workspace/pw-browsers RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q --junitxml=reports/tests.xml`

**154 passed, 0 failed, 0 errors, 0 skipped**, 23.408 seconds. Provider responses are mocked; three simulator tests use real Chromium. The preceding 135-test run also validated Render production environment isolation.

The **19 provider cases** validate Anthropic headers and structured schema, independent review, explicit provider selection, dashboard recognition, refusal/truncation/HTTP errors, original length validation, unsafe content blocks, usage, semantic extraction, offline evaluation key isolation and OpenAI compatibility. Three cloud-deployment cases validate Render HTTPS-origin derivation, secure session/login behavior, a fresh simulator-free background worker and settings persisting across restart; an explicit custom origin overrides the generated platform URL and malformed origins fail closed. This also includes **19 account-traffic cases**, **23 security cases**, **38 mocked Tinder cases**, **6 safe-diagnostic cases**, **3 real Chromium simulator tests**, and **43 other existing cases**. The single pinned Starlette/httpx test-client deprecation warning remains visible.

The first owner-applied Render build failed with 15 fixture-dependent tests because production `SEED_SIMULATOR=false` removed synthetic test threads and `COOKIE_SECURE=true` affected HTTP test sessions. Shared and subprocess fixtures now explicitly select test seeding and cookie policy, while cloud tests continue exercising production behavior. No failing tests or production protections were removed. A restricted-network local TestClient run stalled; it was stopped and rerun with permitted loopback networking. All final test counts above come from the completed run.

The previous 94-test security-hardened validation and XML are preserved in VALIDATION_PRE_TRAFFIC.md and tests_pre_traffic.xml. The historical source archive used for the request-count comparison is dating-agent-security-hardened.zip (SHA-256 d45a73cbf5cc6ec03755d3fc5f2c11cddc3924b33462d8addea13e5f6814b096). Historical artifacts describe earlier code, not current controls.

## New exercised behavior

Durable per-minute/hour request budgets; long/date-form Retry-After values and reconnect cooldown preservation; local budgets distinguished from server throttling; server 503 cooldowns with uncertain single-attempt mutation handling; restriction/verification stops; protocol-failure and repeated-throttling circuit breakers; no double-counting of already-active cooldown checks; caching of inactive histories with refresh on activity changes; global/per-thread quiet pauses; idle polling backoff; deferred uncertain-receipt reconciliation; Tinder-specific send budgets; and one owner-facing activity event on a connection pause.

Prior security, consent, account binding, current-history checks, message POST nonretry, exact-ID read-back, revoked/rejected-draft blocking, session controls, TLS verification, deletion and no-secret-leak tests remain green. The actual Chromium tests still target our fictional local site only.

## Measured request reduction

Ran `.venv/bin/python scripts/benchmark_tinder_traffic.py --baseline /tmp/account-traffic-baseline/dating-agent-browser-c-v3` using MockTransport and fabricated account/message data.

- Two fictional matches; five unchanged ungranted-inbox polls: **20 → 10 HTTP requests**, **50% fewer**.
- One generated, dispatched and exact-ID read-back-verified send: **8 → 6 requests**, **25% fewer**.
- Initial connect/first synchronization: 5 requests in both versions. Message POSTs: 1 in both. Verified sends: 1 in both.

These are request-count measurements for the fixture, not a live account or detection/ban-rate experiment. The benchmark temporarily raises its local test request cap so it finishes immediately; production caps and server cooldown logic are independently tested. The default 180-second polling/900-second idle cap further changes frequency, with a latency tradeoff, but that time-based reduction is not included in the percentages.

## Research, scope and deployment

Official Tinder terms and banned-account guidance plus RFC 6585/9110 were inspected. Fetch URLs, hashes and outcomes are in account_risk_sources.json. No public safe automation rate or reliable prevention of account blocking was established. See ../docs/ACCOUNT_RISK.md for the evidence, application choices and limits.

Python syntax compilation and `docker compose config --quiet` passed. Runtime dependencies are unchanged; the preceding advisory check of 29 pinned Python packages found zero known advisories and zero skipped packages. No Docker build/runtime or image scan was possible because daemon access is unavailable.

No real Tinder account, live model, live Telegram account or SMTP server was accessed during these local automated tests. All Tinder request/send tests use mocked HTTP, and browser tests use only our local fictional site. Hosted read-only troubleshooting probes, if enabled by the operator, are separate from these test results. The implementation does not demonstrate invisibility or a measured reduction in account-ban probability. Platform restrictions and live endpoint compatibility remain unresolved external risks.

Automatic sending remains on by default for an explicitly connected, consented/disclosed Tinder account. Budgets, pause/revoke and restriction stops can defer/block dispatch without requiring approval for every ordinary message. Tinder's account-specific setting does not change Telegram's execution mode.

## Prepared Render hosting path

The native-Python render.yaml uses the documented smallest paid web compute plan (0.5c-512mb), one instance, a 1 GB /var/data disk, generated dashboard credentials and two owner-supplied secret placeholders (now ANTHROPIC_API_KEY and TINDER_AUTH_TOKEN). No fictional simulator or Chromium runs in this hosted configuration. The updated Blueprint passed Render's fetched public JSON Schema. Render CLI 2.36.0 is installed, but separate CLI authentication remains unavailable; plugin OAuth access does not authenticate the CLI. The Render plugin successfully planned the original Blueprint, and the owner applied it; the first hosted build failure is described above. This artifact records local checks before deploying the corrected revision, not a successful cloud or messaging test. See docs/GO_LIVE.md and reports/anthropic_provider_validation.json.

## Reported Connect Tinder failure

Reproduced two failing gzip/deflate profile regressions before fixing the transport: `aiter_bytes()` already decoded the payload, then rebuilding a response with the original Content-Encoding caused a second decode and unhandled httpx.DecodingError. Decoded-response reconstruction now removes wire encoding/length/transfer headers while preserving status, content type and Retry-After. Malformed encoded reads return a controlled protocol error; malformed send receipts remain uncertain and are never retried. Ten compression cases cover profile success, 401/403/429/503 responses, corrupt GET/POST payloads, the decompressed size bound and the exact dashboard connect route.

Six diagnostic tests validate opaque error references, metadata-only logging, database-failure tolerance, read-only profile checks without enabling/sending, redaction and pause behavior. The optional startup check defaults off; its outcome does not prove chat discovery or sending. Deployment and any live profile probe remain separate operational checks.

## Profile access versus inbox authorization

A hosted read-only profile probe succeeded after the compression fix. The owner then connected, but a subsequent synchronization request returned HTTP 401 and the connector correctly paused. This does not establish why the upstream request was refused or prove that a token is merely expired. Connect now checks one bounded inbox page (the same count=60 shape as the worker) before recording/enabling an account. Inbox 401 errors retain a specific code and explanatory dashboard text. Three new regressions cover profile-only access refusal without enabling/sending, an inbox denial pausing future polls, and invalid inbox shape rejection. Existing security fixture responses were expanded to represent the new inbox probe; their autonomy/revocation assertions remain unchanged.

Explicit Connect now includes one additional read-only inbox request. Earlier request-count benchmark results above describe the prior revision's fixture; they have not been rerun as current performance measurements. No messaging success is claimed from the live profile check. The connection remains paused pending a valid session and authorized endpoint access; there is no automatic bypass or retry of the refused access.
