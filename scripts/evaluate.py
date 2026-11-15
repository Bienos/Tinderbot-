"""Reproducible provenance QA, baseline extraction and genuine generated-response rollouts.
Default run makes no provider calls. --live explicitly evaluates configured model; no messaging actions.
"""
import sys,json,csv,hashlib,argparse,tempfile
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent import storage as s,runtime as rt
from agent.engine import generate,prepare_context
from agent.llm import configured as model_configured
from agent.outcomes import detect
BASE=Path(__file__).resolve().parents[1]
def read(name):return [json.loads(l) for l in (BASE/'data'/name).read_text().splitlines() if l.strip()]
def digest(turns):return hashlib.sha256(json.dumps(turns,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def evaluate(live=False,limit=20):
    full=read('full_conversations_augment.jsonl');legacy=read('scenarios_300.jsonl')
    groups=defaultdict(list)
    for r in full:groups[digest(r['turns'])].append(r['id'])
    splits={'train':[],'validation':[],'test':[]}
    for family in sorted({r['family_id'] for r in full}):
        bucket=int(hashlib.sha256(family.encode()).hexdigest(),16)%10
        splits['test' if bucket<2 else 'validation' if bucket<3 else 'train'].append(family)
    def turn_history(r):return [dict(id=f'{r["id"]}-{i}',sender='you' if t['speaker']=='user' else 'them',body=t['text']) for i,t in enumerate(r['turns'])]
    classifications=Counter();label_counts=Counter();confusion=Counter()
    for r in full:
        kinds=[o.kind for o in detect(turn_history(r))];classifications.update(kinds);label_counts[r['expected_outcome']]+=1
        # This is a distribution, not an accuracy claim: corpus labels are coarse, not human gold evidence.
        confusion[(r['expected_outcome'],','.join(kinds) or 'open')]+=1
    import os
    if live and not model_configured():raise SystemExit('--live requires an API key for the selected LLM_PROVIDER')
    saved={key:os.environ.pop(key) for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY') if not live and key in os.environ}
    generated=[]
    try:
        for r in [r for r in full if r['variant']=='independently_authored'][:limit]:
            h=[];steps=[]
            # Only incoming authored turns are supplied. Outgoing turns are actually generated anew.
            for i,t in enumerate(r['turns']):
                if t['speaker']!='match':continue
                h.append(dict(id=f'{r["id"]}-in-{i}',sender='them',body=t['text']))
                d,g=generate(h,{},[],{'language':r['language'],'style':'short casual'},{'mode':'evaluation'})
                steps.append({'input_id':h[-1]['id'],'decision':d.model_dump(),'generator':g})
                if d.action=='reply':h.append(dict(id=f'{r["id"]}-out-{i}',sender='you',body=d.reply))
            generated.append({'id':r['id'],'family_id':r['family_id'],'steps':steps})
    finally:
        os.environ.update(saved)
    # A controlled context-availability ablation; does not measure linguistic performance.
    trials=[]
    for n in (6,14,20,30):
        h=[dict(id=f'm{i}',thread_id='benchmark',sender='them',body='I prefer tea' if i==0 else f'other topic {i}',created_at=s.utcnow()) for i in range(n)]
        rt.retain('benchmark',h);recent=prepare_context(h)['recent_messages'];mem=rt.memory('benchmark')
        trials.append({'turns':n,'recent_has_source_0':any(m['id']=='m0' for m in recent),'memory_has_source_0':any(m['source_id']=='m0' for m in mem)})
        with s.connect() as db:db.execute("DELETE FROM memory WHERE thread_id='benchmark'")
    source_rows=list(csv.DictReader((BASE/'data/research_sources_verified.csv').open(encoding='utf-8-sig')))
    report={'provenance':'All conversations synthetic. Forks share family prefixes. No real dating success measured.',
        'multi_turn_records':len(full),'legacy_records':len(legacy),'unique_ids':len({r['id'] for r in full+legacy}),
        'variants':dict(Counter(r['variant'] for r in full)),'languages_all_full':dict(Counter(r['language'] for r in full)),
        'languages_originals':dict(Counter(r['language'] for r in full if r['variant']=='independently_authored')),
        'exact_duplicate_transcripts':[v for v in groups.values() if len(v)>1],
        'source_catalog_rows':len(source_rows),
        'unresolved_source_references':sorted({sid for r in full for sid in r.get('source_ids',[]) if sid not in {v['source_id'] for v in source_rows}}),
        'placeholder_contact_records':sum('[IG_HANDLE]' in json.dumps(r['turns']) for r in full),
        'languages_legacy':dict(Counter(r['language'] for r in legacy)),
        'legacy_unique_incoming_texts':len({r['incoming_message'].strip().casefold() for r in legacy}),'licensing':'No new third-party transcript redistribution rights inferred; supplied synthetic license unspecified.',
        'coarse_expected_labels':dict(label_counts),'local_parser_classifications':dict(classifications),
        'label_vs_prediction_counts':[{'label':k[0],'prediction':k[1],'count':v} for k,v in sorted(confusion.items())],
        'rollout_mode':'live_model' if live else 'offline_policy_and_demo_only',
        'generated_decision_steps':sum(len(r['steps']) for r in generated),'rollout_transcripts':generated,
        'naturalness_score':None,'human_evaluation':'Not performed; use docs/EVALUATION.md rubric',
        'memory_context_availability_ablation':trials,'memory_ablation_limit':'Source availability only, not quality, cost or causal benefit',
        'family_splits':splits}
    return report
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--limit',type=int,default=20);args=parser.parse_args()
    with tempfile.TemporaryDirectory() as d:
        s.DB_PATH=Path(d)/'eval.db';rt.init();result=evaluate(args.live,args.limit)
    target=BASE/'reports'/('evaluation_live.json' if args.live else 'evaluation_offline.json')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(str(target))
