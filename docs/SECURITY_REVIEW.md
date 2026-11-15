# Manual security review and fixes — 2026-11-15

## Scope, method and evidence

Reviewed the source of the FastAPI dashboard/authentication and webhooks, SQLite persistence, durable worker/action state, model generation/review, per-conversation memory, Playwright simulator, Telegram adapter, OpenDate-derived Tinder adapter, notifications, configuration and deployment files. The target was this supplied application, not unrelated repositories or a live messaging service.

Research used OWASP Session Management, CSRF Prevention, LLM Prompt Injection Prevention and Logging cheat sheets, plus Python's SMTP documentation and the installed Python TLS implementation. The exact fetched URLs, hashes, access outcomes and date are in `reports/security_sources.json`. One attempted Starlette documentation fetch failed and is not treated as inspected evidence.

The Codex Security managed deep-scan tool was unavailable. Its workflow was stopped; **no managed/deep scan, independent third-party audit or exhaustive vulnerability-discovery claim is made**. This report is a manual source review with local regression proofs and an advisory-database check. The model's token consumption for this review is not available; no estimate is presented.

`reports/security_baseline.xml` records 10 deliberately failing pre-fix tests. Some tests combine a confirmed flaw with additional hardening expectations, so this is not a count of 10 independently exploitable vulnerabilities. `reports/privacy_baseline.json` separately reproduces pre-consent Telegram generation eligibility against the previously delivered archive. No real messages, real credentials or external targets were used. Tests use fabricated provider responses.

## Confirmed issues fixed

Severity describes this personal single-owner deployment and its stated preconditions; these are not CVE assignments or externally adjudicated CVSS scores.

| ID / severity | Preconditions and reproduced behavior | Fix and regression evidence |
|---|---|---|
| SEC-01 / High, conditional | An empty/corrupt existing token file made `token()` return an empty string. The absent request credential could then equal the configured credential. This requires a bad local token file; no remote file-write exploit was found. | Validate configured and file-backed credentials, reject empty/non-ASCII/control/oversized tokens; fail startup closed. Generated files must be regular, owned by the process user and owner-only; symlinks are refused. Empty-file and symlink tests cover the boundary. |
| SEC-02 / Medium | Browser cookies contained the reusable master credential. Logout deleted only the browser cookie, so a copied value remained usable; cookie Max-Age did not enforce server-side expiration. | Issue random independent session IDs; store only their hashes with absolute server-side expiry and an owner-token binding. Logout deletes the server record; credential rotation invalidates all sessions. Tests cover credential separation, replay after logout, expiry and rotation. |
| SEC-03 / High integrity | An owner could reject a draft while `execute()` awaited source refresh, yet execution continued using its earlier in-memory pending draft. | Compare-and-set the current pending draft inside the durable action transaction. Rejection/change prevents reservation and dispatch. The refresh-time rejection regression confirms the source message count is unchanged. |
| SEC-04 / High authorization | Telegram's final send path checked connection rights and latest ID but did not recheck thread grants, pause/mode, draft state, profile or complete source revision after reservation. A revoked grant could still produce a POST. | Shared deterministic final dispatch guard and exact current source/profile checks. Six late-change cases (grant, pause, mode, history, profile, draft) now produce zero HTTP sends. A positive reserved-action HTTP contract test remains. |
| SEC-05 / Medium | SMTP STARTTLS used Python's default smtplib context, which in the inspected runtime had certificate verification and hostname checking disabled. An attacker on the SMTP network path could impersonate the server. | Explicit `ssl.create_default_context()` verifies the chain and host. The regression inspects the actual supplied context. No claim of a live SMTP penetration test is made. |
| SEC-06 / Medium scope-control | Connecting Tinder changed the shared mode from supervised to autonomy, which also enabled otherwise granted Telegram threads. This was an unintended cross-platform change rather than an authentication bypass. | Tinder automation is per account and defaults to on as requested. It has a separate on/off control, never changes Telegram mode, and still honors global pause/simulation and consent grants. Tests prove Tinder remains automatic while Telegram stays supervised. |
| SEC-07 / Medium privacy | Telegram jobs could become generation-eligible before a thread consent/disclosure grant. With a configured model, conversation content could leave the installation before that permission. The archived-source reproduction returns eligibility=true without a grant; no real provider call was made. | All live-platform generation requires active connection rights and the owner consent/disclosure grant. Local source synchronization stays separate. A regression checks ineligibility before the grant and eligibility afterward. |
| SEC-08 / Medium availability | The unauthenticated login path and other JSON routes had no body-size boundary before parsing; the webhook checked size only after buffering. Large/chunked input could consume memory. | Outermost ASGI boundary enforces 64 KiB while reading, including chunked data, before parsing, with a total body deadline. Tests verify oversize ordinary and chunked requests return 413. Launchers also bound concurrency/keep-alive. |

## Additional hardening, without inflated exploit claims

- **Host/origin and browser policy:** enforce the configured public authority and reject untrusted hosts. A narrow authenticated private-loopback exception supports the local browser adapter; a private-loopback healthcheck reveals only liveness. CSP no longer allows inline executable scripts/handlers. Fixed asset routes and textContent rendering remain. No independently exploitable DOM-XSS or SQL-injection sink was identified; these are defense-in-depth improvements, not invented XSS/SQL injection findings.
- **Uniform response protections:** login, denied and error responses also receive no-store, nosniff, framing, referrer and CSP headers. HTTPS origins get HSTS and Secure cookies. Unicode credentials fail safely instead of raising compare-digest type errors. Login attempt state is TTL-pruned and bounded.
- **Bounded model authority and cost:** fixed provider endpoint, no model tools or secrets, schema validation and independent review remain. Added 64 KiB model input bound, 768 completion-token bound and durable call budget. Review is probabilistic and can still be fooled; least authority and deterministic permissions provide the operational boundary.
- **Bounded automatic messaging:** durable per-thread and installation hourly send limits protect against runaway volume. Default automatic sending remains enabled for eligible Tinder threads, with no per-message approval. Exhaustion prevents a new dispatch rather than silently relaxing policy.
- **Upstream input and egress:** Tinder pages are bounded to 4 MiB before decoding; message bodies and pagination are bounded. Private tokens remain fixed-host only with no redirects or inherited environment proxies. Model/Telegram HTTP clients also do not inherit proxies. No token harvesting, CAPTCHA handling, stealth or restriction bypass was added.
- **Data minimization:** model-written rationale is no longer copied to metadata activity records. Conversation data remains intentionally private storage; raw provider exceptions/keys are not logged. Session records contain only digests, not master tokens or session bearer values.
- **Container recipe:** read-only root filesystem, dropped Linux capabilities, no-new-privileges and bounded writable temporary space. Runtime validation remains pending because the Docker daemon cannot be accessed here; only Compose configuration was checked.

## Dependency-advisory research

`pip-audit` checked every one of the **29 exactly pinned Python packages** in requirements.lock against its PyPI advisory service: **zero known advisories and zero skipped packages** at execution time. Full machine-readable results are in `reports/dependency_audit_before.json`. The dependency lock did not change, so this is also the dependency result for the fixed code. No package was upgraded merely to make a scanner quiet.

This checks known Python-package advisories only. It is not a container-image, operating-system, Chromium-runtime, supply-chain integrity or unknown/zero-day assessment. A package can be vulnerable without a published advisory. Package names/versions, not chat data or credentials, were submitted to the service.

## Controls reviewed without a validated exploit

Per-owner/per-account message namespacing, thread-local memory and sourced observations; parameterized SQL values and hardcoded table names; authenticated webhook inbox deduplication; source snapshot and profile hashes; durable send/action IDs; single-process ownership lease; no mutation retries on the Tinder POST path; exact-ID read-back and uncertainty quarantine; transactional notification outbox and minimal email content; fixed-origin browser routing; no direct model tool execution; deletion tombstones and configured retention. Passing these tests proves the exercised cases, not all possible attacks.

## Residual risks and deployment requirements

1. **No live provider validation.** Tinder's private interface, Telegram delivery, actual SMTP delivery and real model behavior need authorized live tests with local credentials. Upstream services can change. No scan or fix can guarantee account acceptance or platform availability.
2. **Prompt injection and content quality remain probabilistic.** Deterministic limits prevent unrelated tool execution/permission grants, but a conversational model can still produce unwanted wording, factual errors or inappropriate disclosures from facts the owner provided. Human evaluation, careful profile contents and participant consent remain necessary.
3. **No external exactly-once guarantee.** Tinder/Telegram do not supply a verified atomic compare-and-send contract here. A message can arrive after the last refresh, and a timeout without a provider receipt remains ambiguous. The system blocks further sends rather than guessing/resending.
4. **Storage is plaintext SQLite.** Owner-only local file access is enforced for credentials and protected runtime paths, but real data needs encrypted disks/volumes and encrypted/expired backups. Root/host compromise and provider-side retention are outside these application fixes. Logical deletion does not promise forensic erasure of SQLite free pages or backups.
5. **Single owner and consent attestation.** This is not a hosted multi-tenant service. Owner flags do not independently verify participant age, identity or consent. Keep the dashboard private, terminate TLS correctly, use strong credentials and separate deployments for different owners.
6. **Coverage limits.** Managed deep-scan infrastructure, an independent red team, real-world load testing and container-runtime scanning were unavailable/not performed. The entire code and tested dependencies were reviewed; untested paths and unknown vulnerabilities can remain.

Current full-suite results are recorded in `reports/VALIDATION.md` and `reports/tests.xml`. No statement that the application is “free of all vulnerabilities” is justified.

## Research references

- https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- https://docs.python.org/3/library/smtplib.html
