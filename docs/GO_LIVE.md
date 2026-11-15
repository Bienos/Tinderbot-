# Go live on Render

This repository now includes a Render Blueprint for a small **paid, always-on** Python web service and a **1 GB persistent disk**. The web service also runs the application's background coordinator. No separate worker service or PostgreSQL database is needed for this single-owner setup.

The configuration uses Render's native Python runtime. It disables the fictional simulator and does not download/run Chromium. This changes the simulator deployment only; the Tinder connector still uses its actual HTTP implementation when you connect your account.

## 1. Open the deployment setup

[Open Render deployment setup](https://dashboard.render.com/blueprint/new?repo=https://github.com/Bienos/Tinderbot-)

Sign in/create your Render account. Authorize the repository connection if prompted. Render reads `render.yaml` from this repository's main branch. Select your own intended workspace.

## 2. Add the two requested secrets in Render

- `OPENAI_API_KEY`: your model-provider API key, needed for natural replies.
- `TINDER_AUTH_TOKEN`: your own Tinder account's session credential. This is not your Tinder password. Follow the own-account workflow in docs/TINDER.md/upstream OpenDate documentation; session expiry requires a replacement/reconnect.

**Enter these only in Render's secret/environment UI. Do not paste them into chat, GitHub files, issue comments or screenshots.** The Blueprint contains placeholders, never real credentials.

Render also generates a strong `DASHBOARD_TOKEN`. You will use it to sign into your app after deployment; retrieve it from the service's Environment page. Keep it private like a password.

Do not copy your entire local `.env` into Render. In particular, leave `PUBLIC_ORIGIN` unset to use Render's automatically supplied HTTPS address. If you use a custom domain later, explicitly set `PUBLIC_ORIGIN=https://your-exact-domain` and redeploy.

## 3. Review charges and apply

The proposed resources are:

| Resource | Proposed configuration |
|---|---|
| Web service | 0.5 CPU / 512 MB RAM (`0.5c-512mb`, legacy Starter) |
| Region | Frankfurt; change before creation if you prefer another supported region |
| Persistent disk | 1 GB at `/var/data`; SQLite lives at `/var/data/agent.db` |
| Instances/coordinators | Exactly one |
| Auto-deploy on Git pushes | Off; deploy updates deliberately |

Review the actual current prices in Render before clicking **Apply/Create Blueprint**. Hosting/disk charges and model API charges are separate. No Render resources or billing commitment were created by preparing these files.

A free sleeping/ephemeral service is unsuitable for this application's continuous worker and durable state. The disk persists across restarts, but disk-backed redeployments have a brief service interruption. Render documents disk/snapshot encryption; still restrict access and manage backup retention for relationship data.

## 4. Wait for the service to become Live

Render installs requirements.lock and runs the non-browser automated suite before starting the service. It binds to Render's `$PORT` and checks `/health`. The dashboard's host checks, HTTPS cookies and HSTS derive from Render's documented `RENDER_EXTERNAL_URL` when PUBLIC_ORIGIN is absent.

Wait until Render reports **Live**, then open its generated `https://...onrender.com` address. A queued/building/deploying state is not a successful deployment. If it fails, inspect the first failing build/start log stage; do not paste secrets or environment-variable values into chat.

## 5. Sign in and connect

1. Sign in with `DASHBOARD_TOKEN` from Render's Environment page.
2. Add verified personal facts, language and writing preferences in Settings.
3. Choose **Connect Tinder · automatic replies**, confirming account ownership and the unofficial status.
4. Begin with one consenting adult conversation. Record its one-time consent/disclosure/owner grant in **Automation permissions**. Eligible incoming replies then send automatically; there is no per-message approval.
5. Verify the actual imported messages and provider send/read-back result before enabling other threads. The existing Tinder tests were mocked; no live account was verified during development.

The worker continues after you close the dashboard. Pause/revoke controls remain available. Default polling is three minutes with idle backoff up to fifteen minutes, so discovery is not instantaneous. Budget, cooldown or account-review states can delay/stop dispatch.

## 6. Keep it operable

- Keep one service instance and one ASGI worker; never scale the shared SQLite installation horizontally.
- Watch dashboard account errors, worker progress, uncertain sends and budget/restriction stops.
- Use SQLite's backup API or stop the process for a consistent backup; do not copy only a live `.db` while ignoring its WAL. Protect/expire backups.
- Deploy future main-branch updates manually from Render after reviewing them. Auto-deploy is intentionally off.
- Rotate secrets and reconnect explicitly after session expiry. Do not restore access by blindly retrying an uncertain message.
- For help verifying the actual deployment, share the public Render service URL and nonsecret failure/status information—not credentials.

## What has and has not been checked

The Blueprint has been checked against Render's retrieved public JSON Schema. The Render CLI is installed, but its account-aware validation could not proceed because no CLI workspace is selected/authenticated. Render's dashboard must perform its normal validation when you apply the Blueprint. The local regression suite tests the Render HTTPS-origin configuration, secure login, clean worker startup and settings surviving a restart on persistent local storage.

No paid service was created and no Render deploy was run here. A successful local/schema check is not evidence of a Live deployment. The unofficial Tinder integration remains subject to upstream restrictions, account/session availability and real-world testing; the traffic controls do not guarantee acceptance or prevent blocking.
