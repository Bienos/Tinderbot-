"""QA for synthetic corpus; no third-party private chat data is bundled."""
import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CORPUS = BASE / 'data' / 'full_conversations_augment.jsonl'


def test_new_multi_turn_corpus():
    records = [json.loads(line) for line in CORPUS.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(records) == 400
    assert len({r['id'] for r in records}) == 400
    assert len({r['family_id'] for r in records}) == 200
    kinds = Counter(r['variant'] for r in records)
    assert kinds == {'independently_authored': 200, 'counterfactual_fork_shared_prefix': 200}
    assert all(r['turn_count'] == len(r['turns']) >= 6 for r in records)
    assert all(r['turns'][-1]['speaker'] == 'match' for r in records)
    assert all(r['origin'] == 'original_synthetic_not_real_private_messages' for r in records)
    originals = [r for r in records if r['variant'] == 'independently_authored']
    assert len({r['turns'][0]['text'] for r in originals}) == 200
    assert sum(r['language'] == 'pl' for r in originals) == 168
    assert sum(r['language'] == 'en' for r in originals) == 32


def test_research_catalog_has_no_raw_chat_data():
    import csv
    rows = list(csv.DictReader((BASE / 'data' / 'research_sources_verified.csv').open(encoding='utf-8-sig', newline='')))
    assert len(rows) >= 40
    assert all(r['url'].startswith('https://') for r in rows)
    assert all(r['verified_scope_and_access'] for r in rows)
