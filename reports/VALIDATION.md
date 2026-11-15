# Current validation — Anthropic support and Render build isolation, 2026-11-15

## Executed suite

`SEED_SIMULATOR=false COOKIE_SECURE=true DATING_AGENT_SOURCE=fixture LLM_PROVIDER=anthropic ANTHROPIC_MODEL=claude-sonnet-5-5 PLAYWRIGHT_BROWSERS_PATH=/workspace/pw-browsers RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q --junitxml=reports/tests.xml`

**135 passed, 0 failed, 0 errors, 0 skipped**, 21.805 seconds. Provider calls are mocked. This run deliberately inherits Render's production simulator-disabled and secure-cookie settings to validate test isolation.

The **19 provider cases** validate Anthropic headers and structured schema, independent review, explicit provider selection, dashboard recognition, refusal/truncation/HTTP errors, original length validation, unsafe content blocks, usage, semantic extraction, offline evaluation key isolation and OpenAI compatibility. Three cloud-deployment cases validate Render HTTPS-origin derivation, secure session/login behavior, a fresh simulator-free background worker and settings persisting across restart; an explicit custom origin overrides the generated platform URL and malformed origins fail closed. This also includes **19 account-traffic cases**, **23 security cases**, **25 existing mocked Tinder cases**, **3 real Chromium simulator tests**, and **43 other existing cases**. The single pinned Starlette/httpx test-client deprecation warning remains visible.

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

No real Tinder account, live model, live Telegram account or SMTP server was accessed. All Tinder request/send tests use mocked HTTP, and browser tests use only our local fictional site. The implementation does not demonstrate invisibility or a measured reduction in account-ban probability. Platform restrictions and live endpoint compatibility remain unresolved external risks.

Automatic sending remains on by default for an explicitly connected, consented/disclosed Tinder account. Budgets, pause/revoke and restriction stops can defer/block dispatch without requiring approval for every ordinary message. Tinder's account-specific setting does not change Telegram's execution mode.

## Prepared Render hosting path

The native-Python render.yaml uses the documented smallest paid web compute plan (0.5c-512mb), one instance, a 1 GB /var/data disk, generated dashboard credentials and two owner-supplied secret placeholders (now ANTHROPIC_API_KEY and TINDER_AUTH_TOKEN). No fictional simulator or Chromium runs in this hosted configuration. The updated Blueprint passed Render's fetched public JSON Schema. Render CLI 2.36.0 is installed, but separate CLI authentication remains unavailable; plugin OAuth access does not authenticate the CLI. The Render plugin successfully planned the original Blueprint, and the owner applied it; the first hosted build failure is described above. This artifact records local checks before deploying the corrected revision, not a successful cloud or messaging test. See docs/GO_LIVE.md and reports/anthropic_provider_validation.json.
