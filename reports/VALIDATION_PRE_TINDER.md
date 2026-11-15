# Executed validation — 2026-11-15

## Application and tests

- Python 3.12.14, FastAPI 0.163.0, Playwright 1.65.2, Chromium 159.0.8154.6, pytest 9.2.0, httpx 0.28.1 on Linux x86_64.
- Clean supplied baseline: **14 passed**. Original parser failures reproduced independently in baseline_failures.json.
- Final command: `PLAYWRIGHT_BROWSERS_PATH=/workspace/pw-browsers RUN_BROWSER_E2E=1 .venv/bin/python -m pytest -q --junitxml=reports/tests.xml`.
- Final result: **46 passed, zero failed, zero skipped**, 16.61 seconds in JUnit. **Three real Chromium tests**, 43 other deterministic/integration tests.
- One dependency deprecation warning: Starlette recommends its newer httpx2 test-client transport. Tests passed with the pinned httpx transport; this is not suppressed.
- Real browser evidence: seven-thread discovery with pagination and empty thread, dashboard settings/activity without JavaScript errors, background autonomous simulator send, obsolete draft rejection, source action receipt and text verification in the DOM, and a tab closed after source commit followed by an idempotent retry.
- Native FastAPI startup/shutdown and worker execution were exercised by real subprocess servers. No dashboard sync click was needed for the autonomous browser test.
- Source comparison includes full history and profile/style versions; updated historical content invalidates drafts. Mode revocation during navigation prevents a simulator send at its source transaction.
- `docker compose config --quiet`: **passed**. Docker build/runtime: **not run**, daemon access denied. No workaround against the shared daemon was attempted.

## Dataset and offline evaluation

- Executed `.venv/bin/python scripts/evaluate.py`.
- 300 legacy single-turn cases + 400 multi-turn records; 700 unique record IDs; 200 original families + 200 related forks.
- Original language counts: Polish 168, English 32. Legacy: Polish 290, mixed Polish/English 10.
- Exact duplicate complete multi-turn transcripts: 0. Legacy unique incoming texts: 284 of 300, so repeated incoming wording exists.
- 10 multi-turn records contain placeholder contacts; no concrete contact is fabricated from them. Source catalog: 40 rows; unresolved source references: 0.
- Local-parser distributions and coarse-label disagreements are preserved in evaluation_offline.json. Of seven records labeled date_confirmed, five project confirmed, one suggested, one tentative. This is a limited label comparison, not independently adjudicated accuracy.
- 60 successive generation decisions across 20 authored incoming sequences were executed with no model key. These are **offline policy/demo/abstention decisions**, not tested LLM prose or adaptive human conversation.
- Context-availability ablation: source zero remains in both recent context/memory at 6 and 14 turns; only memory at 20; neither at 30. No causal improvement in linguistic quality is claimed.

## External services and boundaries

- Telegram: official Bot API integration implemented; webhook, owner/rights/revocation and HTTP request/receipt contracts tested with mocks. **No live account or token supplied; no live send claimed.** Prior chat enumeration/history cannot be fetched with this API.
- LLM: structured generation/review/evidence rejection tested with controlled outputs. **No real provider response or human naturalness evaluation.** Missing credentials yield abstention except for the explicitly labeled bounded simulator rule.
- Email: transactional outbox, retries and dedup tested with mocks. **No live SMTP delivery.** Ambiguous delivery is quarantined.
- Tinder: no executor; rejected by dispatch/browser authorization tests. Simulator results imply no Tinder compatibility.
- Independent audit archive: absent from supplied uploads. Prompt-listed regressions reproduced without claiming access to that report.

See ../docs/KNOWN_LIMITATIONS.md for the remaining release work. This validation does not establish real-world dating success or complete production readiness.
