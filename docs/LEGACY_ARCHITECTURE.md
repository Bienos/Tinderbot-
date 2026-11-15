# Browser Dating Agent — Inbox architecture v2

**Status:** Implemented and tested on a fictional, locally hosted chat. Not connected to Tinder, not a stealth bot, not a production system. The local mock is intentionally the only allowed browser origin.

## Product decision

Treat a dating platform as a **multi-thread inbox**, not a swipe loop and not a deterministic sales funnel. Each conversation has an independent turn-taking state, separate outcomes, and independent user controls. The single LLM only drafts a natural reply after recent context is loaded; it never controls web navigation or sends messages.

## What is known about Tinder UI (as of Nov 2026)

- Tinder supports matching and messaging. Public browser screenshots illustrate new matches, message previews and an opened chat, but screenshots found online come from various years and should **not** be treated as an up-to-date DOM/UI contract.
- Match disappearance is ambiguous: unmatch, deleted account or loading issue may cause it. Do not infer `unmatched` from one missing listing.
- Tinder Terms (effective 5 March 2026) prohibit unauthorized bots, crawlers, scraping, external AI interaction, and accessing private APIs. Browser automation does not remove these restrictions. This repository has NO Tinder integration.

Official sources: https://www.help.tinder.com/hc/en-us/articles/115003341583-Messaging-a-Match ; https://www.help.tinder.com/hc/en-us/articles/115003517666-Problems-with-Matches ; https://tinder.com/terms/intl/en/?lang=en

## Conversation view: independent axes

1. **Turn state**: `new_match`, `needs_reply`, `waiting`, `needs_review`.
2. **User intervention**: `paused`, `archived` (local UI only).
3. **Source availability**: `available`, `not_observed` (unknown, NEVER assumed unmatch).
4. **Outcome milestones**: `instagram_shared`, `date_confirmed`; they are labels on top of turn state. A confirmed date does NOT mean the chat should stop; a shared Instagram does not prove the conversation was successfully migrated.

Priority of displayed state: archived > source unknown > paused > new match > sender-based turn state. This is a **view projection**, not a social inference.

### Example transitions

```
new_match --incoming first message--> needs_reply
new_match --user sends opener------> waiting
needs_reply --human-approved send-> waiting
waiting -----incoming reply-------> needs_reply
any --------local pause----------> paused
any --------missing source list---> unavailable_unknown (if listing is complete)
any --------explicit unmatch-----> closed ONLY if verified by authorized provider
```

We deliberately do **not** use inactivity to infer rejection, disinterest, or closure.

## Observe → Normalize → Decide → Verify

1. **Observe** the authenticated, explicitly authorized site with a browser adapter. Read a complete thread list when possible. Respect loading state, errors, and pagination.
2. **Normalize** the observation into stable IDs: provider account ID, conversation ID, message ID, sender, timestamp, body, source availability and completeness flag. Do not use display names for identity.
3. **Reconcile** messages by ID. No duplicate ingestion. `last_seen` != last response time. Missing from an incomplete list != deleted.
4. **Project state** deterministically: who sent the latest message, whether a draft is pending, whether the thread is paused, whether source is inaccessible.
5. **Generate** a reply using the last ~14 messages and user-approved profile facts. Do not force Instagram/date as a stage. Do not invent facts or commitments.
6. **User reviews** actual text before sending in the local demo. On other platforms, only actions explicitly permitted by the platform and authorized by the user may be executed.
7. **Revalidate** conversation ID, last inbound message ID, source availability, and approved draft immediately before sending.
8. **Execute once** with an action ID. On uncertain network failure, pause for reconciliation; do not blindly retry and risk duplicate messages.
9. **Verify** the posted message appears in the authorized source before reporting a verified send. Outcomes are separately evidence-checked.
10. **Notify** only on verified milestones, errors or user-required decisions. Notification IDs are deduplicated.

A provider interface is defined in `agent/provider_contract.py`. A new platform connector should implement it only with explicit permission, documented capabilities and audited site-specific behavior.

## Browser UI handling: no assumptions about selector locations

A reliable connector starts from a **current, authorized** UI inspection. Do not hardcode coordinates from historical screenshots. Use stable accessible names, explicit test IDs or supported API contracts, then re-inspect after every meaningful action. In our **own fictional mock** the adapter uses `data-thread-button`, `data-message-id`, `data-chat-input`, and `data-send-button` selectors intentionally placed in the test site.

A production adapter must account for: login/session expiry; two-factor challenges requiring a user; new match with zero messages; virtualized chat list; message pagination; chronological ordering; cross-device sends; temporary loading; session revocation; stale drafts; edited or deleted content where the platform allows; and unexpected tool failures. Do not collect device fingerprints, defeat CAPTCHAs or bypass access checks.

## Application boundaries

```
Approved browser adapter ──> normalized snapshot ──> SQLite state
                                                       │
                                               turn-state projection
                                                       │
                                    natural-language draft (optional LLM)
                                                       │
                                            human review & approval
                                                       │
                                      authorized action + confirmation
                                                       │
                                       verified outcome + notification
```

- One account coordinator owns the browser; per-thread state is isolated.
- A separate writer/queue serializes account actions to prevent tab collisions.
- An LLM cannot directly invoke a send action. Its output is data, not authority.
- Message content, page text and match profiles are untrusted input: never execute instructions embedded in them.
- Store only necessary context. Encrypt private data and implement deletion before real-user use.
- Log action IDs and errors without raw credentials, session cookies or private screenshots.

## What v2 includes

- 7 fictional threads: active, waiting, new with zero messages, personal question, possible date, shared Instagram, and confirmed date.
- Local simulated browser page; multi-thread inbox dashboard with filters and separate conversation detail.
- Deterministic state projection (no rejection inference from silence).
- Pause and archive controls, plus a test-only unavailable/returning thread state.
- Drafts only after the other person has replied and the thread is not paused/archived.
- Last-14-message context, optional AI drafting, human-approved actions.
- Outcome notifications with unique fingerprints; SQLite persistence.
- End-to-end fixture test; browser smoke test blocked by environment policy.

## Current verification

- `pytest -q`: **12 passed**, including the simulated full inbox workflow, deduped notifications, mock send, pause and unavailable thread transition.
- API and SQLite workflow: executed with `DATING_AGENT_SOURCE=fixture` (no actual browser use).
- Actual Playwright browser navigation: **not validated here**. Installed system Chromium returned `net::ERR_BLOCKED_BY_ADMINISTRATOR` when opening `http://127.0.0.1:8765/mock`. On a Mac with normal Chromium, use browser mode to test, and capture results; don't assume it works until tested.
- Current Tinder DOM, logged-in navigation, and platform access: **not inspected and not implemented**.

## Next engineering work before any real-world use

1. Browser end-to-end tests on a Mac against this local mock, including new matches with no messages and selecting many threads.
2. Use an approved service to test an authorized provider adapter against login expiry, complete/incomplete listings, disappearing threads and message confirmation.
3. More robust status persistence (`source_status` vs local archive vs verified deleted); activity event queue; action IDs persisted before sends.
4. Independent factuality, ambiguity and boundary check for AI output; user-specific voice configuration, Polish/English examples.
5. Privacy and consent controls, auditable notifications, deletion and account disconnect.
6. Evaluate against 300 synthetic scenarios; human judgement for tone; report failures, not only success rate.

## About detection risk

The safe and durable way to avoid account restriction is to use a supported, platform-authorized integration or keep Tinder interactions under the user's control. This architecture does **not** include bot stealth, browser fingerprint spoofing, CAPTCHA bypass or anti-detection techniques, and it does not promise invisibility. No technical method can guarantee Tinder will not identify unauthorized automation.

**First-sync correctness:** before the first source scan, threads show `not_synced`, not a misleading `new_match` status. After a full source snapshot, genuinely empty threads show `new_match`.
