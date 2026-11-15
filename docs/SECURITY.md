# Security and privacy

## Deployment scope

Single adult owner, one installation, one Telegram owner ID and an explicitly bound Tinder owner identity. Do not share an instance across untrusted users. Use separate databases, runtime directories, dashboard tokens and platform credentials. SQLite is plaintext: protect the runtime directory and use an encrypted disk/volume and encrypted backups for real relationship data. The application does not claim application-level database encryption.

The service binds to loopback in local startup/Compose. For Telegram webhooks, publish only `/webhooks/telegram` through a TLS reverse proxy; keep the dashboard behind private access. Set PUBLIC_ORIGIN to the exact dashboard origin and COOKIE_SECURE=true behind TLS. Do not expose development ports publicly. TLS termination is external to this repository.

## Controls

- All private API, simulator and HTML routes require a >=24-character owner token or a random HttpOnly SameSite=Strict session cookie backed by a server-side hashed session record. Sessions expire after 12 hours and logout revokes the current session; cookies never contain the master token. A random 0600 token file is generated if none is configured. Rotate DASHBOARD_TOKEN and restart to invalidate existing cookies.
- The configured public Host is enforced; only authenticated private loopback browser calls and loopback healthchecks have a narrow internal exception. Cookie mutations require same origin or the custom non-simple dashboard request header; cross-origin mutations are rejected. No permissive CORS. Login is rate-limited. Dashboard content is rendered with textContent, never message-derived HTML.
- Business webhooks require a distinct strong secret in Telegram's documented header and a configured owner ID. Unknown or disabled connections fail closed. Updates are deduplicated transactionally and contacts/messages use connection+chat+message namespaces.
- Source chat data is untrusted. No model tools, shell execution, URL following or secret access exist. Generation and independent review can abstain; a model cannot grant itself permissions. Prompt injection is not solved merely by delimiters; limiting authority is the primary boundary.
- No third-party browser sessions are stored. The browser adapter allows only the exact fictional loopback origin and blocks external resource requests. No CAPTCHA, fingerprint, proxy or stealth bypass is included.
- SQLite files are 0600; new runtime directories are 0700. Keep process credentials in the deployment environment/secret manager. `.env`, databases, browser data, logs and virtualenvs are ignored. HTTP/provider exception bodies are not emitted into dashboard errors. Access logs are disabled in the supplied launch commands.
- Global and per-thread pause, explicit participant consent/disclosure, enabled business rights and an owner grant are checked before live sending. Already dispatched requests cannot be recalled.
- Profile changes invalidate pending drafts. Stale messages are rechecked; simulator compare-and-send is atomic. Telegram synchronization is limited by webhook delivery ordering and latency.
- Uncertain delivery blocks further messages in that thread. SMTP uncertain delivery is not automatically retried. Investigate externally before changing durable state; there is intentionally no one-click “resend anyway” control.

## Deletion and retention

Dashboard Delete removes locally stored source/history, memory, jobs, drafts, actions, notifications, outbox and activity for the thread. A tombstone blocks automatic Telegram reimport. External Telegram messages and provider-held data are not deleted by this operation. Tombstones retain the minimum conversation identifier needed to respect deletion.

Inactive observed conversations older than the configured 1–365 day retention period are deleted by the worker, along with old activity/metrics/update dedup records. Backups and underlying SQLite free pages may still contain removed bytes; deletion is logical rather than secure forensic erasure. Back up with SQLite's backup API, expire backups, and use encrypted volumes with appropriate key destruction when required. Stop the process and remove its entire runtime volume to remove all local installation data.

## Remaining risks

A manual source security review, exploit regressions and dependency-advisory check were completed; see SECURITY_REVIEW.md. The managed deep-scan server was unavailable, and no independent external penetration test was performed. Content review is probabilistic; local refusal patterns and outcome parsing have limited linguistic coverage. Consent flags are an owner attestation, not independent participant verification. No minors detection or identity verification service is implemented. Unsupported media pauses a Telegram thread. A deployment serving real users needs an operational privacy/legal review, retention policy, provider data-processing arrangements and human evaluation.

## Unofficial Tinder integration update

The user explicitly replaced the initial Tinder exclusion and requested automatic sending. The implemented OpenDate-derived connector remains unofficial; owner authorization does not establish written Tinder permission. No live credential or live account test was supplied. Tokens are held only in the local environment; connection rows contain a credential fingerprint and public account identity, never the token. Unexpected redirects are rejected, environment proxies are not inherited, and credentials go only to the fixed upstream host. There are no app-mimicking platform headers. Replacing the credential requires reconnecting; unknown sender/account identities fail closed. Participant consent/disclosure and owner grants remain required; connecting enables automatic mode without per-message approval. Message POSTs are not retried, and ambiguous delivery blocks further sends.

## Additional enforced limits

Request bodies are capped at 64 KiB, including chunked requests, before JSON parsing, with a 10-second body deadline. The supplied launchers bound ASGI concurrency and keep-alive duration. Every response, including login and denial responses, receives no-store and framing/content-type/CSP protections. JavaScript is served from fixed same-origin assets; executable inline scripts and handlers are no longer permitted. SMTP STARTTLS uses a default context that verifies both certificate chains and hostnames.

Model context is capped at 64 KiB of serialized input, output at 768 completion tokens, and calls at MODEL_CALLS_PER_MINUTE (default 30). Automatic send budgets default to 60 per thread/hour and 200 across the installation/hour. These budgets are durable and do not require per-message approval. Model-generated rationale is not written into metadata activity logs. Exhaustion abstains/blocks dispatch; it does not grant more authority. Tinder source responses are bounded to 4 MiB per page, with existing bounded pagination and strict identity/content validation.

Tinder account automation defaults to on at connection and can be disabled independently; connecting does not switch Telegram to automatic sending. Both platforms require a consent/disclosure grant before external reply generation. Prompt-injection review remains probabilistic: absence of model tools, isolation, fixed authority and deterministic dispatch limits are the primary security boundaries.
