# Current validation — account traffic controls, 2026-11-15

## Executed suite

`PLAYWRIGHT_BROWSERS_PATH=/workspace/pw-browsers RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q --junitxml=reports/tests.xml`

**116 passed, 0 failed, 0 errors, 0 skipped**, 22.26 seconds in the earlier account-traffic JUnit run. The current complete run took 21.744 seconds.

Three additional cloud-deployment cases validate Render HTTPS-origin derivation, secure session/login behavior, a fresh simulator-free background worker and settings persisting across restart; an explicit custom origin overrides the generated platform URL and malformed origins fail closed. This includes **19 new account-traffic cases**, **23 security cases**, **25 existing mocked Tinder cases**, **3 real Chromium simulator tests**, and **43 other existing cases**. The single pinned Starlette/httpx test-client deprecation warning remains visible.

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

The native-Python render.yaml uses the documented smallest paid web compute plan (0.5c-512mb), one instance, a 1 GB /var/data disk, generated dashboard credentials and two owner-supplied secret placeholders. No fictional simulator or Chromium runs in this hosted configuration. It passed Render’s fetched public JSON Schema. Render CLI 2.36.0 was downloaded from the official release and SHA-256 verified; account-aware CLI validation was blocked by no selected/authenticated CLI workspace. The dashboard must perform normal account validation when the owner applies it. No Render resource or deployment was created. See docs/GO_LIVE.md and reports/render_deployment_sources.json.
