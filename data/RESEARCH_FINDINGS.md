# Tinder / Hinge / Bumble dialogue sourcing — critical research notes

Research snapshot: 2026-11-15.

## Evidence actually found

| Source | What is available | What is NOT available or uncertain | Decision |
|---|---|---|---|
| Alyssa Fernandez — Flirtation Analysis | Public CSV of individual authentic Tinder messages with flirtation labels; author describes ~2,800 selected training messages | No match/thread IDs; not complete conversations; no clear redistribution license; published preview shows repeated messages and apparent first names | Link and summarize; do not redistribute raw text or use as multi-turn benchmark |
| 2023 paper Roca-Cuberes et al. | Analysis of 157 real Tinder conversations and dialogue excerpts | Entire 157-thread dataset not published for unrestricted reuse | Use findings on elicited/volunteered self-disclosure, not entire texts |
| Andersen, The Invitation Game (2024) | Analysis of 41 first-message date-invitation Tinder threads; contextual negotiation | Not an unrestricted raw corpus; paper host says personal download only | Use as source for invitation timing and ambiguity tests |
| Roca-Cuberes / Gibson later paper | Analysis of 157 Spanish Tinder chats | May be same 157-chat corpus as earlier paper: do not add the counts | Do not double count |
| DenSeduct / Russian Romantic Dialogue Dataset | 680 utterance rows and 23 chat indices; self-described as real bot-to-human exchanges | Vendor claims are unverified; possible participant-consent questions; CC BY-NC 4.0 excludes assumed commercial reuse | Keep as linked research example, no rehosting |
| Cornell CANDOR | 1,656 real stranger conversations | Not dating app; full transcripts require author permission | Useful for general natural conversational behavior, not dating conversion |
| SwipeStats | Thousands of user-export-based behavioral records | Standard exports specifically exclude raw conversation text | Use statistics separately, not message training |
| Ashley-Xu repository | 1,209 data rows plus header in Tinder account metadata file; scripts discuss raw conversation data | Raw chats withheld as confidential by author | Do not claim this is a chat transcript collection |
| NYU Tinder Annotation | Annotated-chat method and paper, using Reddit and peer examples | No redistributable annotated conversation rows in repo | Use taxonomy concepts only |
| Polish Reddit conversations | First-person local experiences, complaints, social perceptions | Not representative samples and mostly not full dialogue transcripts | Use for scenario coverage and language sensitivity |
| Reddit r/Tinder, r/Bumble, r/hingeapp screenshots | Public user-submitted screenshots and posts | Potential privacy rights and selection bias; not independently verified; screenshot contents may be unavailable | Link specific posts with clear limits; no screenshot redistribution |

## Why this corpus is synthetic

Finding **hundreds of genuinely public, consent-cleared, sequential Tinder transcripts with rights to redistribute** is a separate data-licensing/recruitment task. A publicly indexed screenshot does not automatically authorize rehosting private messages from both parties. The package therefore separates (1) 40 evidence links with explicit quality notes and (2) freshly authored fictional conversation tests.

## Selection biases that matter

- Viral screenshot posts overrepresent gross, awkward, exceptionally funny or unusually successful chats.
- Posts about dates usually report intentions, not verified follow-through.
- Academic Tinder conversations may be several years old and geographically concentrated (e.g. Spain, Denmark) and should not be treated as Polish 2026 texting norms.
- The real-message repository contains duplicate material and personal names in publicly visible previews; deduplication and PII review would be required before any consented use.
- Many synthetic flirting corpora are poor examples of casual texting, because they over-index on polished lines and a pre-defined funnel.

## Tested functionality and future evaluation

The new dataset contains 200 independently written six-message dialogues (168 Polish, 32 English) and 200 **explicitly related** counterfactual branches (not additional independently sourced chats). Combined with 300 prior single-turn items this yields 700 test records, not 700 distinct natural conversations. All full dialogues end in an incoming match message for agent reply evaluation. All user and match names, Instagram references and place references are fictional or generic. No Tinder credentials or private conversations were accessed.

Automated QA passed (`14 passed`) for project logic and corpus format. This is a **structural**, not linguistic or statistical validity, result. Human scoring and consent-cleared real-world tests are still needed. Particularly useful next collections would be voluntary opt-in data from two consenting participants or a licensing agreement for appropriately anonymized thread-level exports.

## Recommended follow-up for real chat research

Secure consent from **both** participants to use de-identified full chat histories, store explicit rights for research/training, split by user/match across test and train to prevent data leakage, redact private information, and record only objectively verifiable outcomes. Make a separate gold evaluation dataset that has never been used for model tuning.

## Sources

See `research_sources_verified.csv` (40 linked entries with content classification and limitations). Examples of high-value indexes:

- https://github.com/alyssafrndz/Flirtation-analysis
- https://discovery.ucl.ac.uk/id/eprint/10170934/
- https://portal.findresearcher.sdu.dk/files/282418164/TheInvitationGame_manusforInternetPragmaticsspecialissue.pdf
- https://huggingface.co/datasets/DenSeduct/Russian_Romantic_Dialogue_Dataset
- https://convokit.cornell.edu/documentation/candor.html
- https://www.reddit.com/r/Tinder/
- https://www.reddit.com/r/PolskaNaLuzie/comments/1uxexre/randkowanie/
