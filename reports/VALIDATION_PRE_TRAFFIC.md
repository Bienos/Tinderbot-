# Current validation — security hardening, 2026-11-15

## Executed tests

Command: `PLAYWRIGHT_BROWSERS_PATH=/workspace/pw-browsers RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q --junitxml=reports/tests.xml`

**94 passed; 0 failed; 0 errors; 0 skipped**, 19.62 seconds in JUnit. This includes **23 security cases**, **25 mocked Tinder contract/application cases**, **3 real Chromium simulator tests** and **43 other existing tests**. One pinned Starlette/httpx test-client deprecation warning remains; it was not hidden.

The previous 71-test OpenDate delivery's report and XML are preserved as VALIDATION_PRE_SECURITY.md and tests_pre_security.xml. Historical reports describe earlier behavior, not current controls. The original 46-test and clean-upload 14-test evidence remain separate.

The new security tests initially produced **10 failures** in the pre-fix code (security_baseline.xml). This includes additional hardening expectations and is not a claim of 10 independently exploitable vulnerabilities. A separate archived-source check showed Telegram generation eligibility without a consent grant (privacy_baseline.json), with no real model call. Eight confirmed application issues and their fixes are documented in ../docs/SECURITY_REVIEW.md.

## Security fixes exercised

- Invalid/empty/symlinked credential files fail closed; Unicode invalid credentials are rejected safely.
- Browser sessions use independent random IDs with hashed server records, expiration, logout revocation and owner-token rotation binding. Cookies do not contain the master credential.
- Host/origin checks and security headers cover login, denial and normal responses. Ordinary/chunked oversized request bodies are rejected before JSON parsing. Browser scripts are fixed same-origin assets; inline execution is forbidden by CSP.
- The private authenticated browser adapter/healthcheck still works behind a configured HTTPS public origin. Untrusted public hosts and cross-site writes remain rejected.
- Draft rejection during refresh blocks dispatch atomically. Telegram late grant/pause/mode/history/profile/draft changes produce no send.
- SMTP uses certificate and hostname verification. Model input/call budgets and durable automatic-send budgets prevent new dispatch when exhausted.
- Neither Telegram nor Tinder content is externally drafted before the thread consent/disclosure grant.
- Tinder automatic sending remains on by default for an explicitly connected account, with an independent on/off control; connecting Tinder does not change Telegram mode. Global pause and simulation still prevent live sends.
- The three actual Chromium tests pass with the stricter CSP and extracted JavaScript, including dashboard controls and autonomous fictional sending.

## Research and dependencies

Manual source review and OWASP/Python documentation research were completed. The managed Codex Security deep-scan server was unavailable, so no managed scan or exhaustive/no-vulnerabilities claim is made. Source URLs/hashes are in security_sources.json.

`pip-audit` checked the exact requirements.lock: **29 Python packages, zero skipped, zero known published advisories**. Full JSON is dependency_audit_before.json; the lockfile was unchanged by security fixes, so it also applies to this delivery. This does not scan container/OS/Chromium vulnerabilities or unknown vulnerabilities.

## Operational checks and remaining limits

Python syntax compilation and `docker compose config --quiet` passed. The hardened container recipe now drops capabilities, enables no-new-privileges, uses a read-only root filesystem and a bounded temporary filesystem. Docker daemon access is unavailable, so no container build/runtime or image vulnerability scan was performed.

Native temporary Uvicorn servers and worker/browser flows ran successfully. All Tinder/Telegram/SMTP/model security cases use fabricated credentials/responses; **no live messaging account was accessed or messaged**. Live private-endpoint compatibility, provider delivery and human conversation evaluation remain unverified.

SQLite data still requires encrypted disks/volumes/backups for production relationship data. Prompt injection cannot be eliminated by a second model review; least authority, deterministic guards and resource limits bound its operational impact. Remote atomic compare-and-send/exactly-once guarantees remain unavailable; ambiguous delivery stays quarantined. See ../docs/SECURITY_REVIEW.md and ../docs/KNOWN_LIMITATIONS.md for scope and residual risk.
