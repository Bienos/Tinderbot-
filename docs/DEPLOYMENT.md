# Setup and deployment

For the prepared hosted path, use [GO_LIVE.md](GO_LIVE.md) and the repository’s render.yaml. It runs natively on Render with one persistent disk, simulator disabled, and credentials entered through the provider UI. Review paid resources before applying.

## One-command local startup

From the project directory run `./run.sh` (Python 3.12+, network access for packages/Chromium). On Linux, missing shared browser libraries may require `playwright install-deps chromium` through your OS package manager. Open http://127.0.0.1:8765 and sign in using `runtime/dashboard-token`, or set your own DASHBOARD_TOKEN. The worker starts automatically, in supervised mode. Choose simulation in Settings for autonomous fictional messaging.

`.env.example` documents variables. Copy to `.env` and edit as needed. `run.sh` installs the exact tested lockfile; its shell-level DATING_AGENT_SOURCE/PLAYWRIGHT_BROWSERS_PATH control browser installation. The server also loads `.env`. No model key is needed to exercise infrastructure; natural responses to arbitrary input need a configured model.

## Docker

`docker compose up --build -d` starts one worker/server with persistent runtime volume and a loopback published port. Optional `.env` is supported by recent Compose. To retrieve a generated token: `docker compose exec agent cat runtime/dashboard-token`. Check `docker compose logs agent` and `/health`. The Docker daemon was inaccessible in the execution environment, so this image/Compose recipe was not built or runtime-validated here; the native Python/Chromium application was.

The image version matches requirements.lock's Playwright version. Run only one ASGI worker; do not use `--workers >1` or share its volume with another active installation. The process lease expires after 120 seconds on abrupt failure. A second process must not reset in-flight actions before acquiring the lease.

## Tinder (OpenDate-derived, automatic sending)

Follow [TINDER.md](TINDER.md). Configure TINDER_ENABLED and TINDER_AUTH_TOKEN locally; restart; connect in Settings. Connection enables automatic replies only for this Tinder account, with no per-message approval for consented/disclosed threads. No live Tinder validation was possible without credentials. The unofficial integration can break or lead to account restrictions; it is not represented as platform-approved.

## Telegram Business

1. Create/manage a bot with BotFather and enable the supported Telegram Business connection capability. Confirm your account's current capabilities with Telegram; a personal account login token is not a bot credential.
2. Set TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID and a random >=24-character TELEGRAM_WEBHOOK_SECRET. These are server-side values, not dashboard fields.
3. Make only `/webhooks/telegram` reachable via a public HTTPS reverse proxy. Keep the owner dashboard private. Configure a webhook with Telegram's official `setWebhook` method, including `secret_token` and `allowed_updates`: `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`. Never place the bot token in tickets, browser history or logs.
4. Connect the bot in Telegram Business settings, select eligible private chats and grant reply rights. The application learns connections and new messages from updates. It cannot import arbitrary prior histories or enumerate all existing chats through this API.
5. In each eligible dashboard thread, record participant consent and disclosure and enable the owner grant. In Settings choose supervised or authorized_autonomy. Test supervised first with consenting adults. Autonomous mode then needs no per-message approval.
6. Test a message, revocation and expiration of reply rights. Verify Telegram receipts and notifications independently before broader use. Credentials were not supplied here; live testing is still required.

## Model, email and operational checks

Set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` and optionally `ANTHROPIC_MODEL` for Claude structured generation and independent review. The Render Blueprint defaults to `claude-sonnet-5-5`. OpenAI remains supported through `LLM_PROVIDER=openai` and `OPENAI_API_KEY`/`OPENAI_MODEL`. See [LLM_PROVIDERS.md](LLM_PROVIDERS.md). `SEMANTIC_OUTCOMES=true` opts into additional model-based outcome extraction with the selected provider; validate its quality before relying on it. Set actual per-million pricing to make cost metrics meaningful; zero means unpriced, not free. A live smoke call and human review of both Polish and English remain necessary.

Enable email in Settings and configure SMTP_HOST/PORT, sender, recipient and optional authentication. STARTTLS is required. Notifications contain no names/contact/time/place/chat text. Dashboard delivery works without SMTP. SMTP setup failures retry; ambiguous sends are quarantined. No live SMTP receipt was obtained during development.

Back up with SQLite's online backup API or after stopping the service; copying a running `.db` without its WAL is unsafe. Protect and expire backups. Monitor dashboard worker errors, failed jobs/actions, uncertain deliveries and outbox states. `/health` indicates process liveness; `/api/state` exposes authenticated worker progress and metrics, not an external readiness guarantee.

## Reproducible validation

```bash
.venv/bin/python -m pytest -q
RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q
.venv/bin/python scripts/evaluate.py
# Explicit model evaluation, never sends to a messaging platform:
.venv/bin/python scripts/evaluate.py --live --limit 20
```

Browser tests need a free loopback port 8765 and installed Chromium. Set PLAYWRIGHT_BROWSERS_PATH to your installation if needed. Tests launch and clean up temporary servers/databases. Deterministic tests do not contact Telegram, SMTP or an LLM provider.

## Security deployment notes

Set PUBLIC_ORIGIN to the exact browser-facing origin (including a nondefault port). Preserve its Host at the TLS proxy and keep private APIs off public ingress. The server rejects other hosts; an authenticated loopback-only browser exception preserves the fictional browser adapter and a loopback healthcheck exception reveals only liveness. HTTPS origins automatically use Secure session cookies and HSTS. Rotate the master token to invalidate all issued sessions; logout revokes the current session immediately. A corrupt, empty, symlinked or overly permissive generated token file fails closed; replace it deliberately before restart.

The Compose recipe now drops capabilities, enables no-new-privileges and a read-only root filesystem, with only the runtime volume and bounded /tmp tmpfs writable. Compose configuration was validated; actual container/browser operation under these new restrictions still needs deployment testing because Docker daemon access is unavailable here. Use an encrypted runtime volume and encrypted/expired backups for real messages. Security budgets and their variables are documented in .env.example.

## Account traffic profile

Update an existing .env explicitly to adopt the new example values: TINDER_POLL_INTERVAL=180, TINDER_IDLE_POLL_INTERVAL=900, TINDER_INACTIVE_THREAD_REFRESH=3600, TINDER_REQUESTS_PER_MINUTE=30, TINDER_REQUESTS_PER_HOUR=300, TINDER_SENDS_PER_THREAD_HOUR=10, TINDER_SENDS_PER_HOUR=20, TINDER_SENDS_PER_DAY=100. They are conservative application budgets, not Tinder-approved thresholds. Existing .env values are preserved. Automatic sending remains enabled for eligible connected Tinder threads; budget exhaustion defers new dispatches and restriction signals stop the account connection. See ACCOUNT_RISK.md for latency and live-validation limits.
