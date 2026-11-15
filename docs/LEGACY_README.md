# Dating Agent C — Authorized Browser Agent (Local Working Prototype)

**Purpose:** demonstrate browser-driven conversation ingestion, short context memory, AI reply drafting, human approval, outcome verification and notifications on a **fictional local chat site**. All people and conversations are synthetic.

**Not included:** Tinder integration, account credentials, detection evasion, autonomous impersonation or automatic Tinder messaging. Tinder's terms prohibit unauthorized AI-powered third-party access. For a real external website, written permission and a reviewed site-specific adapter are prerequisites.

## Quick start (Mac/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
# Optional: cp .env.example .env and export the values in your shell.
uvicorn app:app --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765/**. Click **Sync conversations using browser**. The backend starts a real Chromium browser, clicks each fictional conversation and reads the DOM. A draft is generated only when the newest message is from the other person. Demo-mode without OPENAI_API_KEY contains only limited illustrative responses; full natural-language draft generation needs an API key.

On this test site, click **Approve & send in mock** to authorize the browser to post a single draft. Re-running sync creates no duplicate drafts or notifications. You can independently inspect the source site at **http://127.0.0.1:8765/mock**.

### Optional LLM

```bash
export OPENAI_API_KEY='...'
export OPENAI_MODEL='gpt-4.1-mini'
```

The model receives up to the latest 14 messages per fictional conversation and optional user-provided facts. Do **not** upload third-party private messages without suitable permission. External API retention and data processing are determined by the model provider's policies.

### Optional e-mail on newly verified outcomes

```bash
export SMTP_HOST='your SMTP host'
export SMTP_PORT='587'
export SMTP_USERNAME='your user'
export SMTP_PASSWORD='your app password'
export NOTIFY_TO='your address'
export NOTIFY_FROM='your address'
```

If not configured, notifications appear only in the local dashboard. Test by syncing the three fictional threads: one open conversation, one explicitly offered Instagram handle, and one mutual, fully specified meeting. For meetings, **both sides must mention the same ISO date, time and place**, and the other person must explicitly agree. This conservative demo parser is not a production-grade natural-language verification system.

### Run unit tests

```bash
pytest -q
```

### Files

- `app.py` — API and approval gate
- `agent/browser.py` — Playwright browser automation with hardcoded local mock restriction
- `agent/engine.py` — conversation drafting prompt, short-memory context window, optional LLM
- `agent/outcomes.py` — conservative social/contact/date result parsing
- `agent/storage.py` — SQLite messages, drafts, unique/idempotent events
- `agent/notify.py` — optional SMTP notification
- `static/mock.html` — fictional source site controlled by browser
- `static/dashboard.html` — review/approval dashboard
- `data/scenarios_300.jsonl` — 300 **synthetic** evaluation situations from earlier research
- `tests/test_core.py` — basic deterministic checks

### Architecture and the next engineering increment

```text
Approved browser adapter → Source conversation snapshot → SQLite short memory
     → LLM draft → Factual/boundary check → User approval / platform-authorized execution
     → Verify external action/result → Notification
```

For a production integration, use a platform that explicitly supports automation, document the scope of authorization, add audited selectors/actions, authentication/session isolation, async queue, trace IDs, independent hallucination and consent checks, privacy retention controls, secure secret storage, handling of revoked access and a robust evaluation set. One background worker per account, not per conversation; no arbitrary delay/fingerprint spoofing.

Stagehand v4 is a sensible later upgrade for frequently changing **authorized** websites: https://www.browserbase.com/stagehand . It is *not* necessary for our stable test fixture: Playwright is simpler, more predictable and cheaper here.

### Security scope

- The starter only runs browser actions against `http://127.0.0.1:8765`.
- `BROWSER_ALLOWED_ORIGINS` cannot bypass the hardcoded mock-only restriction.
- Web server must remain bound to `127.0.0.1`, not the public internet.
- Never commit the Chrome profile, database or `.env`.
- Messages are fictional seed data; real conversation records require consent, expiry/deletion, access controls and privacy review.
- E-mails and LLM calls are disabled unless credentials are deliberately configured.
- User approval is required for each browser-sent draft in this version.
- The 300 scenarios are **test inputs**, not scraped user chats or a validated training corpus.

## Status

This is a runnable **engineering skeleton**, not a validated, deployable dating service. It is suitable for demonstrating the workflow and building more comprehensive tests; substantial privacy, quality and operational work is required before any production use.

### Test in restricted execution environments

Some managed Chromium installations have an administrative `URLBlocklist` that prevents **all** page navigation, including local pages. The browser component cannot be tested in those environments. For testing **only the orchestration and persistence layer** without any browser:

```bash
export DATING_AGENT_SOURCE=fixture
uvicorn app:app --host 127.0.0.1 --port 8765
```

The dashboard will then use synthetic fixture data directly. This is *not a browser agent test*. Disable fixture mode on your own Mac to run Playwright with its bundled Chromium. The exact browser-control end-to-end workflow has not been verified in this managed environment.

## Version 2: Multi-conversation inbox (2026-11-15)

**New:** see [ARCHITECTURE.md](ARCHITECTURE.md) for the state model and authorized browser integration contract. The dashboard is now a multi-thread inbox with filters (new matches, needs reply, waiting, other), per-thread chat view, outcomes, pause and archive controls. No Tinder access, detection evasion or unauthorized automation was added.

```bash
# Full deterministic API and notification demo; no Chrome required
DATING_AGENT_SOURCE=fixture ./run.sh

# Browser automation on your Mac against the fictional test site only
./run.sh

# Tests
pytest -q
```

The fixture now has **seven fictional conversations** rather than three, including a brand-new match without messages. The browser reader handles empty message lists; deterministic status projection separates awaiting replies from independently verified outcomes. Once a user approves a message in fixture mode, the synthetic source is updated without running a browser. Fixture mode is not a browser test. Use actual browser mode on a Mac to verify Playwright behavior.

**Verification:** 12 tests passed. Browser smoke test was blocked by Chromium admin `URLBlocklist` (`net::ERR_BLOCKED_BY_ADMINISTRATOR`), so browser control remains unverified in this environment. Use `DATING_AGENT_SOURCE=fixture` for the verified control-plane flow.

**First sync:** conversation states remain `not_synced` until observed. This prevents mistakenly marking an unseen existing conversation as a new match.

## Corpus update v3 (research-based, synthetic; 2026-11-15)

The `data/` folder now also includes `full_conversations_augment.jsonl` and `.csv`: **200 independently authored, six-message fictional chats** (168 Polish / 32 English), and **200 counterfactual forks** sharing prefixes with those chats. In addition, `research_sources_verified.csv` lists **40 inspected public research/dataset/forum sources** with source type and limitations. Original `data/scenarios_300.jsonl` stays unchanged. Use these for evaluating conversation memory, boundaries, responsiveness and outcome extraction. **The new multi-turn transcripts are not copied from Tinder; none has independently verified real-world dating outcomes.**

A separate downloadable research corpus package includes a combined import file with 700 total test entries (300 legacy single-turn + 400 full multi-turn records), a full source catalog and reproducible counts. Execute `pytest -q tests/test_corpus_v3.py` to verify corpus integrity.
