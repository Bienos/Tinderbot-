# Dating Conversation Corpus v3 — research + multi-turn augmentation

**Created:** 2026-11-15. **Data provenance:** Synthetic full conversations, not transcripts copied from real dating-app accounts. They are independent illustrative examples and counterfactual branches influenced by publicly documented interaction patterns. Links and annotations to authentic source materials are kept separately.

## What changed

- **200 independently authored fictional multi-turn conversations**, each with at least 6 messages (user and match).
- **200 counterfactual forks**, each reusing the same initial context but changing the ending. These are NOT 200 independent conversations.
- **40 catalogued public sources**, with the evidence type, access limits and usefulness annotated.
- Previous **300 single-turn scenarios** kept unchanged, in a combined JSONL file with explicit `record_type` labels.
- **Total 700 evaluation records**, but only 200 newly independently authored multi-turn source scenarios. No false claim of real chat data.

## Files

`full_conversations_augment.jsonl` — nested `turns` format for evaluation.
`full_conversations_augment.csv` — readable full dialogue rows, UTF-8 with BOM for Polish spreadsheet programs.
`research_sources_verified.csv` / `.json` — primary academic, available datasets and individual forum posts, each linked.
`combined_legacy_300_plus_full_augmentation.jsonl` — merged legacy single-message situations + new multi-turn scenarios.
`qa_summary.json` — inventory/verification counts.

## Authentic-source limitations

The **Flirtation-analysis** GitHub project describes about **2800 authentic individual Tinder messages** with flirtation labels. A published CSV is visible, but it is not a set of sequential threads, and the repository has no clear license granting redistribution. Therefore its raw message text has NOT been copied into this package. 40 source entries include some discussion posts and screenshots (not necessarily full or independently verified chats). No scraping of private accounts was performed.

The **157-conversation** and **41-conversation** academic corpora are not available in full as redistributable raw files. The 157 conversations may be the same underlying sample across multiple papers; do not add the article counts. **SwipeStats** regular downloadable files contain aggregate behavior, not raw message text. **Russian Romantic Dialogue Dataset** claims 23 AI-to-human dialogues and 680 utterances, but provenance, participant consent and outcome verification are unverified, and it uses the **CC BY-NC 4.0** license, incompatible with assumed commercial reuse.

## Research-driven quality tests

1. **Truthfulness:** do not invent personal experiences; any first-person factual claim must come from user profile or conversation history.
2. **Context:** use latest 6-14 turns, not a huge long-term RAG store for short chats; keep verified meeting arrangements separately.
3. **Opportunity:** invitation timing follows real context, not a required message number. Refusals and hesitations override goals.
4. **Grounding:** Instagram handles and dates are outcomes only when actually shared/accepted, never extracted from third-party references or conditional wording.
5. **No stale send:** if a new message arrives after drafting, invalidate and recompute.
6. **No unauthorized platform access:** these files test a conversational engine; they do not authorize Tinder automation.

## Bias warning

Publicly shared screenshots disproportionately feature awkward, funny, offensive or unusually successful experiences. They are **not representative** of general online dating, and cannot be used to claim conversion rates. Self-reported Reddit outcomes are unverified. The constructed dialogues intentionally include false positives, rejections, ambiguous meeting plans and everyday low-stakes chat.
