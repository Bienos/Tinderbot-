# Evaluation and provenance

## Evidence levels

- **Original baseline:** 14 supplied tests passed in a clean extraction. They did not detect the known cancellation/contact failures.
- **Reproduced failures:** reports/baseline_failures.json records the original parser retaining a confirmed date after cancellation, extracting a third-party contact, extracting a refused contact and missing a simple informal agreement.
- **Deterministic/integration:** expanded tests exercise outcome chronology, informal agreement, rescheduling, new empty threads, stale drafts, independent histories, source-linked memory/deletion/retention, permissions, duplicate sends, lost receipts, unknown-delivery blocking, model-output validation and outbox behavior. Provider HTTP/SMTP responses and model outputs are mocked where indicated.
- **Real browser:** opt-in tests launch a real temporary Uvicorn server and Chromium, traverse seven threads including pagination/empty threads, use dashboard settings/activity, perform autonomous background sending, reject a newer-source stale draft, verify a direct send in the DOM and close a tab after the source commits a send. No external dating platform is involved.
- **Offline rollouts:** scripts/evaluate.py invokes the actual generation pipeline successively with each authored incoming turn; outgoing authored turns are not replayed. With no key these are policy/demo/abstention decisions, **not live language-quality evaluation**. Authored incoming turns are fixed inputs, not adaptive human counterparts. Default: 20 original families, three decision steps each.
- **Live model / human / real participants:** not performed. No credentials or consenting live accounts were provided. Naturalness score remains null.

The current suite has **116 passing tests**, including three cloud-deployment cases, 19 account-traffic cases, 23 security cases, 25 existing mocked Tinder tests and three real Chromium simulator tests. The current executed suite is recorded in reports/VALIDATION.md and reports/tests.xml. The prior 46-test suite is preserved as a historical baseline before Tinder integration. The executed suite summary and environment are in reports/VALIDATION.md; the JUnit output is reports/tests.xml. Run commands are in DEPLOYMENT.md.

## Corpus QA

`reports/evaluation_offline.json` is generated from supplied source files. It records 300 legacy scenarios, 400 multi-turn records, 200 independent families, 200 related forks, language distributions, exact full-transcript duplicates, placeholder contacts, source-reference integrity and coarse-label versus local-parser counts. All material is synthetic. There are 168 Polish and 32 English originals; forks are dependent examples, not independent observations. The separate uploaded corpus package and project data overlap intentionally and must not be added as independent samples.

The supplied source catalog has 40 rows. Preserve source IDs and limitations in `data/RESEARCH_CORPUS_README.md`, `RESEARCH_FINDINGS.md` and `research_sources_verified.csv`. The package does not establish general commercial redistribution rights for third-party transcripts; no raw external conversation was downloaded. Some referenced research corpora are restricted or noncommercial. Synthetic-package licensing itself was not specified and must not be assumed.

Split by `family_id` so original/fork prefixes never cross train/test. The evaluation script produces stable hash-based family splits. These are evaluation aids, not a new held-out benchmark: the supplied corpus already influenced development. No model was trained on it here.

Corpus outcome labels are not evidence-annotated adjudicated gold labels. `[IG_HANDLE]` cannot yield a usable actual contact. Implicit cafes or unspecified meridiem cannot yield a calendar booking. Distribution counts are reported without treating all disagreements as system errors or claiming outcome accuracy from these labels alone.

## Memory ablation

Controlled histories of 6, 14, 20 and 30 incoming turns compare availability of the first source in recent context versus bounded observations. At 6/14 both retain it; at 20 only the 24-observation memory retains it; at 30 neither retains it. This supports a bounded context-availability claim only. It does not demonstrate improved naturalness, factual accuracy or cost-effectiveness. For the typical six-turn supplied chats, extra memory has no demonstrated benefit; recent observations are excluded from the extra model context.

## Required human rubric

Use at least two bilingual raters, blind to model/configuration, with separate scores for each dimension (1 unacceptable, 3 usable with edits, 5 natural/accurate). Include Polish/English, uncertainty, jokes/sarcasm, short replies, topic changes, invitations, rejections, cancellations and conflicting facts. Preserve source IDs and record disagreements; resolve critical boundary/factual disputes by adjudication. Do not average a critical safety failure away.

| Dimension | Rater/evidence question |
|---|---|
| Context/coherence | Does the reply address the latest turn and relevant prior context? |
| Naturalness | Would this wording fit this exchange, without forced polish, slang or questions? |
| Factual accuracy | Are all personal details/commitments supported by the verified profile? |
| Style alignment | Does the reply match the owner's language and stated preferences? |
| Initiative | Is any invitation/contact suggestion contextually appropriate, with no fixed funnel? |
| Boundaries | Are refusal, uncertainty, privacy and disclosed mediation respected? |
| Outcome accuracy | Do evidence IDs support the exact active/cancelled state and contact ownership? |
| Memory accuracy | Is remembered content sourced, correctly attributed and still current? |
| Reliability | Is execution correctly authorized, fresh, verified and free of duplicate sends? |

Record generation latency, input/output tokens and configured cost alongside human ratings. Compare recent-history-only versus memory at matched scenarios, randomize order and report failures/uncertainty. Model-as-judge scoring may supplement but cannot replace this exercise. No synthetic test result establishes real-life dating success.

## Requested failure mapping

1. Confirmation later cancelled: temporal cancellation tests and current-outcome projection.
2. Old agreement before later proposal: scoped-assent regression.
3. Third-party handle: attribution rejection tests.
4. Refusal plus handle: refusal regression.
5. Informal agreement: cross-turn day/time/place regression.
6. Empty new match: API and real browser tests.
7. Incoming before older draft: service and source/browser freshness tests.
8. Crash during send: durable uncertain receipt recovery plus real tab-close-after-commit test.
9. Retried notification: outbox setup-failure retry/dedup test.
10. Simultaneous chats: independent thread histories/memory and autonomous tick test.
11. Incorrect personal fact: deterministic claim rejection, independent review and changed-profile invalidation tests.
12. No response needed: explicit boundary/no-reply and waiting-turn tests.

The legacy test assertions were expanded to allow newly supported tentative/suggested outcomes while still rejecting false confirmed dates; legacy checks were retained. Tests are not removed to conceal failures.

## OpenDate/Tinder integration update

`tests/test_tinder.py` runs the actual connector/application orchestration against httpx.MockTransport, including automatic sends without approval, false/old/missing receipts, transport failure, rate limits, session expiry, identity binding, final context refresh, revocation, source disappearance and redaction. All responses are mocked. This exercises implemented code but does not verify current private endpoints or a live Tinder account. The three real browser tests still target our own fictional site. Connecting Tinder automatically selects the application’s autonomy mode; one-time consent/disclosure grants remain separate.

The manual security review and reproduced/fixed issues are documented in SECURITY_REVIEW.md. The original failing security regression artifact is preserved in reports/security_baseline.xml; it is intentionally historical and does not describe the current passing suite.

The account-traffic benchmark measures requests against a fictional MockTransport source, not a detection or ban rate. See ACCOUNT_RISK.md and reports/account_traffic_benchmark.json.
