#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
.venv/bin/pip install -q -r requirements.lock
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$PWD/runtime/browsers}"
if [[ "${DATING_AGENT_SOURCE:-browser}" == "browser" ]]; then .venv/bin/playwright install chromium; fi
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765 --no-access-log --limit-concurrency 100 --timeout-keep-alive 5
