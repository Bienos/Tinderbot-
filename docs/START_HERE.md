# Put the conversation agent into use

Use the latest bundle: **dating-agent-account-controls.zip**. It contains the complete updated application. The two originally uploaded ZIPs and earlier delivery bundles are superseded.

## Recommended first step: run locally

GitHub is optional for this step. On macOS/Linux with Python 3.12+, or Windows using WSL:

1. Extract dating-agent-account-controls.zip. Open a terminal in the extracted dating-agent-browser-c-v3 directory.
2. Copy .env.example to .env. Keep .env private. Set OPENAI_API_KEY locally for natural replies. To enable the unofficial Tinder connection also set TINDER_ENABLED=true and your own TINDER_AUTH_TOKEN. Never paste the token or API key into chat or commit them.
3. Run `./run.sh`. If your extractor removes its executable bit, use `bash run.sh`. It installs dependencies/Chromium and starts the app. Linux may require OS browser dependencies as explained in docs/DEPLOYMENT.md.
4. Open http://127.0.0.1:8765. Sign in using the generated runtime/dashboard-token, or the DASHBOARD_TOKEN you configured locally.
5. In Settings, enter verified personal facts/preferences, then use Connect Tinder. Automatic replies are on for the Tinder account after connection; one-time per-thread participant-consent/disclosure grants are still required. No per-message approval is required. Start with one consenting adult test conversation and inspect actual read/send receipts before enabling more threads.
6. Keep this process and computer running. Closing the dashboard does not stop the worker; stopping the process/computer does.

For a clean Tinder-only deployment, set SEED_SIMULATOR=false before the first start with a fresh database. `DATING_AGENT_SOURCE=fixture ./run.sh` skips Chromium installation; that variable controls only the local simulator adapter, not Tinder's HTTP connector. With simulator seeding off there are no fictional threads to process. Do not delete an existing private database just to change startup settings.

Without credentials the app can still demonstrate its simulator. No live Tinder account was tested in the supplied delivery. The connector is unofficial; tests and traffic controls do not guarantee account acceptance or prevent blocking.

## GitHub: source storage, not continuous hosting

Create an **empty private repository** at https://github.com/new, for example Bienos/dating-agent. Do not initialize it with a README if you want a straightforward first upload. Give the assistant the repository URL and it can upload the prepared source through the connected GitHub account.

Upload the extracted project source, not just the ZIP. Include .gitignore and .env.example. Exclude .env, runtime/, .venv/, databases, browser/session data and real messages. The bundled corpus is synthetic; reports use fictional test data.

GitHub Pages cannot run this Python application or its background worker. GitHub Actions is suitable for tests, not a permanent personal messaging worker.

## Continuous operation

Use an always-on server/VPS or a compatible container host with persistent storage. This app needs:

- One running server/coordinator process per database.
- Persistent, protected runtime storage for SQLite and credentials; encrypted disk/backups for real private messages.
- Secure environment variables or a host secret manager.
- A private dashboard, or TLS with an exact PUBLIC_ORIGIN and appropriate access protection.
- Restart supervision and error monitoring.

compose.yaml and Dockerfile are supplied. `docker compose up --build -d` is the intended container workflow. Compose configuration and native startup were tested; the Docker image/runtime was not executed because daemon access was unavailable in the development workspace. Validate the hardened image on the chosen host before using real data. Hosting/model charges require your provider/account choices; none have been provisioned.

The current workspace can be used to finish setup, upload to a chosen repo, prepare deployment and inspect results. It is temporary and is not a reliable permanent hosting service.

## Existing evidence and instructions

- README.md: overview and startup.
- docs/TINDER.md: own-account connection, automatic sends and limitations.
- docs/DEPLOYMENT.md: native/container deployment and secrets.
- docs/ACCOUNT_RISK.md: conservative request controls and their limits.
- docs/SECURITY_REVIEW.md: security research, fixes and residual risks.
- reports/VALIDATION.md: 113 passing tests, including three actual Chromium simulator tests. Tinder tests are mocked, not live compatibility evidence.
