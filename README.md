# Conversation Agent · OpenDate Tinder Integration

A working single-owner FastAPI application for independent conversations, permission-based autonomous execution, a local fictional browser chat, a Telegram Business integration, and an optional unofficial Tinder connector adapted from OpenDate.

## Go live online

[Open the Render deployment setup](https://dashboard.render.com/blueprint/new?repo=https://github.com/Bienos/Tinderbot-) using the committed render.yaml. It proposes one small paid Python service plus a persistent disk, configured for Anthropic Claude. Enter secrets only in Render, review charges and apply; then follow the [go-live walkthrough](docs/GO_LIVE.md). Creating a service does not verify live messaging; check its deploy status and account configuration separately.

## Start

```bash
./run.sh
```

Open **http://127.0.0.1:8765**. Sign in with `runtime/dashboard-token`, or configure a strong `DASHBOARD_TOKEN` in `.env`. The background worker initially starts in **supervised** mode. Connecting Tinder enables **automatic sending** for eligible Tinder conversations, as requested, without changing Telegram’s mode. In Settings, select **simulation** to let it automatically reply on the fictional platform. Without a model key, one labeled demonstration rule can reply to the seeded weekend conversation; other messages request owner knowledge. This is deliberately not presented as a full offline conversational model.

For natural-language replies, set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` and optionally `ANTHROPIC_MODEL` (default `claude-sonnet-5-5`). OpenAI remains supported with `LLM_PROVIDER=openai`, `OPENAI_API_KEY` and optionally `OPENAI_MODEL`. See [provider setup](docs/LLM_PROVIDERS.md) and [.env.example](.env.example). Generation includes recent thread history, verified personal facts, preferences, feedback and source-linked observations, followed by independent factual/boundary review. Live model quality was not evaluated without credentials.

Alternatively, `docker compose up --build -d` provides the deployment recipe. The native Python/Chromium flow was executed; Docker daemon access was unavailable, so the container build is unverified.

## Connect Tinder with automatic sending

Configure `TINDER_ENABLED=true`, your own `TINDER_AUTH_TOKEN` and the selected model provider's API key, then restart. In **Settings → Tinder**, choose **Connect Tinder · automatic replies**. The worker discovers matches and messages. Set each intended thread's consent/disclosure grant once; replies then send without per-message approval. Pause/revoke controls remain available.

The connector is unofficial, adapted from OpenDate with MIT attribution. Live Tinder compatibility is **not yet verified** because no credential was supplied. It never retries a message POST and requires a provider message ID verified in thread history. See [Tinder setup and behavior](docs/TINDER.md).

## What is implemented

- Authenticated inbox, per-thread history/context, current outcomes, activity and reliability metrics.
- Settings for language, writing style, verified personal facts, feedback, retention, email and execution mode.
- Global pause/resume, per-thread pause/archive, regeneration, deletion and Telegram permission/revocation controls.
- A background coordinator, durable SQLite jobs/actions, stale-draft checks, action IDs and uncertain-delivery quarantine.
- Real Chromium discovery, pagination, thread selection, extraction, sending and DOM receipt verification on our fictional local site.
- OpenDate-derived Tinder match/message discovery, automatic reply execution, account binding and exact-ID read-back verification.
- Telegram Business webhook ingestion, update deduplication, edited/deleted messages, namespaced account/thread storage, rights/recency/consent gates and official `sendMessage` execution.
- Independent model generation/review, explicit abstention, bounded per-thread observations and profile-version checks.
- Temporal date/contact outcomes with evidence; optional semantic model extraction. Cancellations replace current confirmations.
- Transactional in-app notifications and an SMTP outbox with backoff and ambiguous-delivery quarantine.
- The supplied synthetic corpus, family-aware evaluation splits, offline rollout tooling and regression/browser tests.

## Execution modes

| Mode | Behavior |
|---|---|
| Supervised | Owner approves validated drafts; live channels still require participant consent/disclosure and a thread grant. |
| Simulation | Automatic fictional replies, including real browser execution; no live-platform autonomy. |
| Authorized autonomy | Automatic replies in enabled Tinder/Telegram threads with disclosure, participant consent and owner grants; Telegram additionally requires business reply rights and a recent incoming message. The mode name is an internal permission setting, not a claim that Tinder authorizes this integration. |

There is no automatic follow-up when the latest message is ours. An empty new conversation is discovered but does not invent profile details or an opener. Pause/revocation cannot recall an external request already dispatched.

## Validate

```bash
.venv/bin/python -m pytest -q
# Requires installed Chromium and a free loopback port 8765:
RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q
.venv/bin/python scripts/evaluate.py
# Explicit provider evaluation, never sends messages:
.venv/bin/python scripts/evaluate.py --live --limit 20
```

The corpus is **200 authored synthetic conversations + 200 related forks + 300 earlier synthetic scenarios**, not real Tinder conversations. Placeholder contacts and implicit places cannot establish usable real-world outcomes. Deterministic, browser, offline policy, live-model and human evaluation results are reported separately in [docs/EVALUATION.md](docs/EVALUATION.md).

## Layout

```text
app.py                     authenticated dashboard/API, webhook, coordinator lease
agent/adapters.py          simulator, browser, Telegram and Tinder dispatch
agent/tinder.py            OpenDate-derived unofficial connector and read-back verification
agent/browser.py           deterministic loopback-only Playwright controller
agent/service.py           background orchestration and durable execution
agent/runtime.py           jobs/actions/settings/memory/outcomes/outbox/metrics
agent/storage.py           preserved SQLite message/draft/fixture foundation
agent/engine.py            structured generation and independent review
agent/llm.py               native Anthropic/OpenAI structured-output transports
agent/outcomes.py          temporal local and optional semantic outcome extraction
agent/notify.py            minimal SMTP delivery and retries
static/                    dashboard and fictional chat platform
data/                      supplied synthetic corpus and source catalog
scripts/evaluate.py        provenance QA, generated rollouts, context ablation
tests/                     deterministic, API, failure, security and browser tests
reports/                   baseline failures, evaluation and validation artifacts
docs/                      architecture, decisions, security, deployment and limits
```

Read [deployment instructions](docs/DEPLOYMENT.md) for Telegram setup and local/container operation, [security boundaries](docs/SECURITY.md) before storing real messages, and [known limitations](docs/KNOWN_LIMITATIONS.md) for incomplete validation. The independent audit ZIP named in the brief was not supplied; failures listed in the prompt were reproduced and covered without claiming access to that audit.

## Security review

The manual [security review and fixes](docs/SECURITY_REVIEW.md) cover revocable sessions, credential-file validation, dispatch/revocation races, consent before model calls, verified SMTP TLS, scoped Tinder autonomy, strict browser/request boundaries and model/send budgets. The current test results and dependency-advisory artifact are in reports/. This is not a guarantee that every possible vulnerability has been found; live Tinder and container-runtime security remain unverified.

## Account traffic controls

The [account-risk research and controls](docs/ACCOUNT_RISK.md) reduce redundant requests, cache inactive threads, back off when idle, honor server cooldowns and pause on restriction signals. A mocked comparison measured 50% fewer unchanged-poll requests and 25% fewer requests per verified send. Automatic sending remains enabled for eligible threads. No reduction in actual detection or ban probability has been measured.
