# Current validation — OpenDate Tinder update, 2026-11-15

## Scope change

The user explicitly replaced the original Tinder exclusion with “Ok change it and use this” (OpenDate), then requested “No let’s have automated sending on”. The implementation now includes an owner-enabled unofficial Tinder connector; the previous disabled-only decision is superseded. Automatic sending is selected on connection for consented/disclosed threads, with no per-message approval. This is not a claim of platform permission.

## Executed result

Command: `PLAYWRIGHT_BROWSERS_PATH=/workspace/pw-browsers RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q --junitxml=reports/tests.xml`

**71 passed; 0 failed; 0 errors; 0 skipped**, 18.51 seconds. Of these, **25 Tinder connector/application contract tests** use mocked HTTP and **3 browser tests** use real Chromium against the fictional local platform. The remaining 43 cover the existing core, API, corpus, privacy and reliability behavior. One pinned Starlette/httpx test-client deprecation warning remains; it was not suppressed.

The prior 46-test report and JUnit artifact are preserved in VALIDATION_PRE_TINDER.md and tests_pre_tinder.xml. The clean original uploaded application's 14-test baseline and reproduced parser failures remain separate evidence.

Environment: Python 3.12.14, FastAPI 0.163.0, Playwright 1.65.2, pytest 9.2.0, httpx 0.28.1, Linux x86_64. The exact dependency lockfile is unchanged; no OpenDate dependency tree or remote executable package was added.

## Tinder coverage (offline)

- Successful account connection selects automatic mode; match discovery includes empty threads.
- Automatic reply dispatch occurs with no approval endpoint/click, after the thread consent/disclosure grant.
- Repeated worker ticks do not send duplicates; no live demo-rule replies are permitted.
- Only a newly returned concrete provider ID verified in thread history with outgoing sender identity and exact text is a confirmed send.
- POST timeouts after source commit, 5xx responses, absent receipts and preexisting message IDs are quarantined, with exactly one POST attempt.
- A known receipt with delayed visibility can later be reconciled by that exact ID; receiptless uncertainty blocks later incoming-turn dispatch.
- An incoming message during processing and revocation between refresh and dispatch block the send.
- Global pause, thread consent, session expiry, account identity mismatch and credential replacement are enforced.
- Rate limits suspend network requests; read-only 5xx retries and pagination caps/cycles are covered.
- Unsupported media/unknown sender and incomplete message history fail closed without overwriting a known complete history.
- Missing matches remain unknown, not inferred unmatches; deleted threads are not reimported.
- Owner ID pinning, redirection rejection, public-state/token redaction and authenticated connect/revoke API behavior are covered.

All Tinder requests used `httpx.MockTransport`, fabricated identities and a fabricated token. Read-only environment checks confirmed no live Tinder credential and no local `.env` were present. **No real Tinder login, match fetch or message send was attempted.** Current endpoint compatibility, account restrictions and session lifetime remain unverified on a live account.

## Existing regression coverage

The three actual Chromium tests still verify seven-thread pagination/extraction, empty threads, dashboard settings/activity without JavaScript errors, autonomous worker sending, source-side stale-anchor rejection, DOM action-ID/text verification, a tab closed after source commit and idempotent retry. The Settings browser check also verifies the new Tinder connect control is disabled when credentials are absent. These tests imply no Tinder browser compatibility.

The corpus remains 200 authored synthetic conversations + 200 related forks + 300 legacy synthetic cases. The offline evaluation and human-evaluation limits are unchanged; evaluation_offline.json is not a live-model conversation score.

## Deployment and external services

`docker compose config --quiet` passed. Container build/runtime remains unverified because daemon access is denied. Native temporary Uvicorn servers and background workers were executed by tests.

Live Tinder, Telegram, model-generated conversation quality, SMTP delivery and human evaluation remain pending credentials/participants. See ../docs/TINDER.md for the actual local configuration and automatic-send behavior and ../docs/KNOWN_LIMITATIONS.md for remaining release work.
