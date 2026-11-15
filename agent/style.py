"""Style library: few-shot examples of good replies for the drafting model.

Sources, in order of weight:
1. The owner's own sent replies observed in live conversations (their real voice).
2. The bundled corpus in data/full_conversations_augment.jsonl: 400 synthetic dialogues
   (200 originals + 200 counterfactual forks). The corpus is fictional; it teaches tone, length
   and rhythm only. Examples are passed as STYLE references, never as facts about the owner.

Selection is lexical (word + character-trigram overlap) so it runs offline with no embedding API.
"""
from __future__ import annotations

import json
import os
import re
import statistics
from functools import lru_cache
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / 'data' / 'full_conversations_augment.jsonl'
PL_HINT = re.compile(r"[ąćęłńóśźż]|\b(nie|jest|się|czy|jak|co|to|mam|masz|już|też|że|był|była|ale)\b", re.I)
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
WORD = re.compile(r"\w+", re.U)


def language_of(text: str) -> str:
    return 'pl' if PL_HINT.search(text or '') else 'en'


STOP = set("""a i w z na do to że ze się nie tak jak co czy ale już też mi mnie ci cię ty ja on ona my wy jest są był była było
mam masz ma o od po za przez dla tylko jeszcze bardzo może no też tam tu teraz kiedy który która które bo albo lub
the a an and or to of in on at is are was were i you me my your it this that for with be have do so just not but""".split())


def _stem(word: str) -> str:
    return word[:5] if len(word) > 5 else word


def _features(text: str) -> dict:
    words = [w for w in WORD.findall((text or '').lower()) if len(w) >= 3 and w not in STOP and not w.isdigit()]
    stems = {_stem(w) for w in words}
    grams = {'#' + w[i:i + 3] for w in words for i in range(max(1, len(w) - 2))}
    return {'stems': stems, 'grams': grams, 'len': len(text or '')}


def _cos(a: set, b: set) -> float:
    return len(a & b) / ((len(a) * len(b)) ** 0.5) if a and b else 0.0


def _similarity(a: dict, b: dict) -> float:
    score = 0.7 * _cos(a['stems'], b['stems']) + 0.3 * _cos(a['grams'], b['grams'])
    return score * (0.5 if b['len'] < 12 else 1.0)  # one-word messages ("tak") match everything; damp them


@lru_cache(maxsize=1)
def corpus_pairs() -> tuple[dict, ...]:
    """(incoming message -> owner-side reply) pairs from the bundled corpus, de-duplicated."""
    pairs, seen = [], set()
    if not CORPUS.exists():
        return ()
    for line in CORPUS.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        conv = json.loads(line)
        turns = conv.get('turns') or []
        for i, turn in enumerate(turns):
            if i == 0 or turn.get('speaker') != 'user' or turns[i - 1].get('speaker') != 'match':
                continue
            them, reply = turns[i - 1].get('text', '').strip(), turn.get('text', '').strip()
            if not them or not reply or (them, reply) in seen:
                continue
            seen.add((them, reply))
            context = [t.get('text', '') for t in turns[max(0, i - 4):i - 1]]
            pairs.append({'id': f"{conv.get('id')}#{i}", 'source': 'corpus', 'lang': conv.get('language') or language_of(them),
                          'theme': conv.get('theme', ''), 'them': them, 'reply': reply,
                          'feat': _features(them + ' ' + ' '.join(context[-2:]))})
    return tuple(pairs)


def own_pairs(exclude_thread: str | None = None) -> list[dict]:
    """The owner's real replies from synced conversations (simulator excluded)."""
    from agent import storage as s
    rows = s.rows("SELECT m.thread_id,m.sender,m.body,m.created_at FROM messages m JOIN threads t ON t.id=m.thread_id "
                  "WHERE t.platform!='simulator' ORDER BY m.thread_id,m.created_at")
    pairs, prev = [], None
    for r in rows:
        if prev and prev['thread_id'] == r['thread_id'] and prev['sender'] == 'them' and r['sender'] == 'you' \
                and r['thread_id'] != exclude_thread and r['body'].strip():
            pairs.append({'id': 'own', 'source': 'own', 'lang': language_of(prev['body'] + ' ' + r['body']), 'theme': '',
                          'them': prev['body'].strip()[:300], 'reply': r['body'].strip()[:300], 'feat': _features(prev['body'])})
        prev = r
    return pairs


def select_examples(history, *, language: str = 'auto', exclude_thread: str | None = None,
                    k: int | None = None) -> list[dict]:
    """Pick the k most situation-similar examples; own replies first, corpus fills the rest."""
    k = k or int(os.getenv('STYLE_EXAMPLES', '8'))
    incoming = [m['body'] for m in history if m['sender'] == 'them'][-2:]
    if not incoming:
        return []
    lang = language if language in ('pl', 'en') else language_of(incoming[-1])
    query = _features(' '.join(incoming))
    own = own_pairs(exclude_thread)
    pool = [(p, _similarity(query, p['feat']) + (0.15 if p['source'] == 'own' else 0.0) + (0.05 if p['lang'] == lang else -1.0))
            for p in list(own) + list(corpus_pairs())]
    pool.sort(key=lambda x: (-x[1], x[0]['id']))
    chosen, replies, own_count = [], [], 0
    max_own = max(1, k // 3) if own else 0
    for p, score in pool:
        if score < 0 or len(chosen) >= k:
            break
        if p['source'] == 'own' and own_count >= max_own:
            continue
        rf = _features(p['reply'])['grams']
        if any(_cos(rf, r) > 0.6 for r in replies):
            continue  # keep examples diverse, not near-duplicates of each other
        chosen.append({'them': p['them'], 'you': p['reply'], 'source': p['source']})
        replies.append(rf)
        own_count += p['source'] == 'own'
    return chosen


@lru_cache(maxsize=2)
def canon_text(language: str = 'pl') -> str:
    """A fixed, deterministic set of corpus examples placed in the cached system prompt."""
    pairs = [p for p in corpus_pairs() if p['lang'] == language] or list(corpus_pairs())
    by_theme: dict[str, list[dict]] = {}
    for p in sorted(pairs, key=lambda p: p['id']):
        by_theme.setdefault(p['theme'], []).append(p)
    picked = []
    while len(picked) < 36 and any(by_theme.values()):
        for theme in sorted(by_theme):
            if by_theme[theme] and len(picked) < 36:
                picked.append(by_theme[theme].pop(0))
    lines = ['STYLE CANON. Fictional example exchanges showing the desired voice: short, casual, specific to what '
             'she said, light humour, no interview-style question chains. Style reference only: never reuse their '
             'facts, places, plans or names, and never copy a line verbatim.']
    for p in picked:
        lines.append(f"them: {p['them']}\nyou: {p['reply']}")
    return '\n\n'.join(lines)


def style_stats(examples: list[dict] | None = None, own: list[dict] | None = None) -> dict:
    """Measurable voice features of the owner's replies (or the corpus when no own replies exist yet)."""
    own = own_pairs() if own is None else own
    source = own if len(own) >= 15 else list(corpus_pairs())
    replies = [p['reply'] for p in source] or ['']
    lengths = [len(r) for r in replies]
    return {'based_on': 'own_messages' if source is own else 'corpus', 'samples': len(replies),
            'median_chars': int(statistics.median(lengths)),
            'lowercase_start_pct': round(100 * sum(1 for r in replies if r[:1].islower()) / len(replies)),
            'question_pct': round(100 * sum(1 for r in replies if r.rstrip().endswith('?')) / len(replies)),
            'emoji_pct': round(100 * sum(1 for r in replies if EMOJI.search(r)) / len(replies)),
            'laugh_pct': round(100 * sum(1 for r in replies if re.search(r'\b(xd+|haha\w*|hah\w*|lol)\b', r, re.I)) / len(replies))}


_SUMMARY: dict = {}


def library_summary() -> dict:
    """What the Settings → Style card shows. One pass over the messages, cached until a message is added."""
    from agent import storage as s
    key = tuple(s.rows("SELECT COUNT(*) n, COALESCE(MAX(m.synced_at),'') last FROM messages m JOIN threads t ON t.id=m.thread_id "
                       "WHERE t.platform!='simulator'")[0].values())
    if _SUMMARY.get('key') != key:
        corpus, own = corpus_pairs(), own_pairs()
        stats = style_stats(own=own)
        _SUMMARY.update(key=key, value={'corpus_pairs': len(corpus), 'corpus_pl': sum(1 for p in corpus if p['lang'] == 'pl'),
                                        'own_pairs': len(own), 'stats': stats, 'suggested_style': suggested_style(stats)})
    return dict(_SUMMARY['value'])


def suggested_style(st: dict | None = None) -> str:
    """A plain-language style description derived from measured features, for the owner to accept or edit."""
    st = st or style_stats()
    parts = [f"krótko, zwykle około {st['median_chars']} znaków, jedno-dwa zdania"]
    parts.append('od małej litery' if st['lowercase_start_pct'] >= 60 else 'zdania od wielkiej litery')
    parts.append('bez emoji' if st['emoji_pct'] < 5 else 'emoji z umiarem')
    if st['laugh_pct'] >= 10:
        parts.append('czasem „haha" albo „xd"')
    parts.append('pytanie tylko gdy naturalne, bez serii pytań' if st['question_pct'] < 55 else 'często kończ lekkim pytaniem')
    parts.append('reaguj konkretnie na to, co napisała, lekki humor, bez komplementów na siłę')
    return ', '.join(parts)
