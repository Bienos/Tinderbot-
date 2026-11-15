"""Event ingestion, isolated generation, guarded execution and background orchestration."""
import asyncio,contextlib,json,os,time
from uuid import uuid4
from agent import storage as s,runtime as rt
from agent.adapters import adapter,StaleAction
from agent.engine import generate,should_draft
from agent.llm import configured as model_configured
from agent.outcomes import detect,semantic
from agent.tinder import TinderRejected
from agent.dispatch import DispatchDenied
from agent.limits import check_send_budget,BudgetExceeded

LOCK=asyncio.Lock()   # drafts, consent and sending. Held per job or per owner click, never across a long network sync.
SYNC=asyncio.Lock()   # one Tinder/Telegram synchronization at a time; its network waits happen here, not under LOCK
TICK=asyncio.Lock()   # one full tick() at a time
WAKE=asyncio.Event()  # set to start the next background cycle at once (e.g. the owner asked for a new draft)


class Busy(Exception):
    pass


@contextlib.asynccontextmanager
async def owner_lock(wait=25):
    """An owner click waits briefly for the job in progress (seconds) instead of failing or hanging."""
    try:await asyncio.wait_for(LOCK.acquire(),wait)
    except asyncio.TimeoutError:raise Busy('Coordinator busy')
    try:yield
    finally:LOCK.release()
WORKER={'running':False,'last_tick':None,'error':None}
SHUTTING_DOWN=False  # set on SIGTERM: no new background work while the process drains

def thread_by_id(tid):return next((t for t in s.threads() if t['id']==tid),None)

def ingest(thread,items):
    for m in items:s.sync_message(m)
    hist=s.messages(thread['id'])
    if hist:
        with s.connect() as db:
            db.execute("UPDATE drafts SET status='stale' WHERE thread_id=? AND anchor_message_id!=? AND status='pending'",(thread['id'],hist[-1]['id']))
        rt.retain(thread['id'],hist)
        old=s.rows('SELECT anchor FROM outcome_state WHERE thread_id=?',(thread['id'],))
        if not old or old[0]['anchor']!=hist[-1]['id']:
            outcomes=detect(hist)
            # Default deterministic temporal baseline; semantic mode explicitly enabled, with evidence checks.
            # Live semantic calls occur in process_job to keep sync nonblocking.
            rt.record_outcomes(thread['id'],hist[-1]['id'],outcomes)
        if should_draft(hist) and rt.eligible(thread):rt.enqueue(thread['id'],hist[-1]['id'])
    return hist

async def sync_all():
    total=0
    sim=[t for t in s.threads() if t['platform']=='simulator']
    if sim:
        if os.getenv('DATING_AGENT_SOURCE','browser')=='fixture':remote={t['id']:s.source_for_thread(t['id']) for t in sim if t['source_visibility']=='available'}
        else:
            from agent.browser import read_mock_threads
            remote=await read_mock_threads()
        for t in sim:
            if t['id'] in remote:
                s.set_thread_flags(t['id'],visibility='available')
                with s.connect() as db:db.execute('UPDATE threads SET source_seen=1 WHERE id=?',(t['id'],))
                ingest(thread_by_id(t['id']),remote[t['id']]);total+=len(remote[t['id']])
            else:s.set_thread_flags(t['id'],visibility='not_observed')
    for t in s.threads():
        if t['platform']=='telegram':
            items=await adapter(t).snapshot(t);ingest(t,items);total+=len(items)
    from agent.tinder import poll
    await poll()
    rt.metric('messages_observed',total)
    return total

async def process_job(job):
    t=thread_by_id(job['thread_id'])
    if not t or not rt.eligible(t):rt.job_end(job,'cancelled');return
    hist=s.messages(t['id'])
    if not hist or hist[-1]['id']!=job['anchor']:rt.job_end(job,'stale');return
    existing=s.rows('SELECT * FROM drafts WHERE thread_id=? AND anchor_message_id=?',(t['id'],job['anchor']))
    if not existing or existing[0]['status']=='regenerate':
        cfg=rt.settings();context_hash=rt.settings_hash(cfg);history_hash=rt.history_hash(hist)
        # Raw observations repeat recent history only when older than the model window.
        from agent.engine import context_window
        from agent import style
        recent={m['id'] for m in hist[-context_window():]}
        memory=[m for m in rt.memory(t['id']) if m['source_id'] not in recent]
        examples=style.select_examples(hist,language=cfg['language'],exclude_thread=t['id'])
        incoming=[m['body'] for m in hist if m['sender']=='them'][-1:]
        lang=cfg['language'] if cfg['language'] in ('pl','en') else style.language_of(incoming[0] if incoming else '')
        from agent import strategy
        outcome_rows=s.rows('SELECT value FROM outcome_state WHERE thread_id=?',(t['id'],))
        plan=strategy.analyze(hist,cfg,json.loads(outcome_rows[0]['value']) if outcome_rows else [])
        profile={**cfg['profile'],**strategy.planning_facts(cfg)}
        decision,generator=await asyncio.to_thread(generate,hist,profile,memory,
             {'language':cfg['language'],'style':cfg['style'],'feedback':cfg['feedback']},
             {'platform':t['platform'],'mode':cfg['mode'],'disclosure_required':True},
             examples,style.style_stats(),style.canon_text(lang),plan)
        # Asked about AI: only an honest admission may go out; anything else waits for the owner.
        if decision.action=='reply' and rt.ai_question(incoming[0] if incoming else '') and not rt.AI_MENTION.search(decision.reply or ''):
            decision.action='requires_user';decision.note='Zapytała o AI. Odpowiedź musi to przyznać: '+(decision.reply or '')
        if t['platform']!='simulator' and generator=='demo_rule (not AI)':
            decision.action='requires_user';decision.reply='';decision.note='Configure a model for live replies';generator='demo_placeholder'
        if existing:
            with s.connect() as db:db.execute("UPDATE drafts SET body=?,generator=?,status='pending',created_at=? WHERE id=?",
                (decision.reply or decision.note,generator,s.utcnow(),existing[0]['id']))
        else:s.upsert_draft(t['id'],job['anchor'],decision.reply or decision.note,generator)
        d=s.rows('SELECT * FROM drafts WHERE thread_id=? AND anchor_message_id=?',(t['id'],job['anchor']))[0]
        with s.connect() as db:db.execute('INSERT OR REPLACE INTO draft_context VALUES(?,?,?)',(d['id'],context_hash,history_hash))
        if decision.action!='reply':s.set_draft_status(d['id'],'no_reply' if decision.action=='no_reply' else 'needs_user')
        rt.audit(t['id'],'draft_'+decision.action,'Response policy evaluated; details remain in the draft')
        significant={'date_confirmed','date_rescheduled','date_cancelled','instagram_shared','phone_shared'}
        if os.getenv('SEMANTIC_OUTCOMES','false')=='true' and model_configured() and not any(o.kind in significant for o in detect(hist)):
            try:
                extracted=await asyncio.to_thread(semantic,hist)
                if extracted:rt.record_outcomes(t['id'],job['anchor'],extracted)
            except Exception:rt.metric('semantic_outcome_failures')
    d=s.rows('SELECT * FROM drafts WHERE thread_id=? AND anchor_message_id=?',(t['id'],job['anchor']))[0]
    t=thread_by_id(t['id'])
    if d['status']=='pending' and t and rt.auto_allowed(t):await execute(d['id'],automatic=True)
    rt.job_end(job,'done');rt.metric('jobs_completed')

async def execute(draft_id,automatic=False):
    d=s.draft_by_id(draft_id)
    if not d or d['status']!='pending':raise StaleAction('Draft already resolved or unavailable')
    t=thread_by_id(d['thread_id'])
    if not t or not rt.eligible(t) or (automatic and not rt.auto_allowed(t)):raise PermissionError('Permission revoked or conversation paused')
    if d['generator'] not in ('demo_rule (not AI)',) and not d['generator'].startswith('LLM-reviewed:'):raise PermissionError('Draft not validated')
    if s.rows("SELECT 1 FROM actions WHERE thread_id=? AND status IN ('sending','uncertain')",(t['id'],)):
        raise StaleAction('Earlier delivery uncertain; reconcile before sending more')
    context=s.rows('SELECT * FROM draft_context WHERE draft_id=?',(d['id'],))
    if not context or context[0]['settings_hash']!=rt.settings_hash():
        s.set_draft_status(d['id'],'stale');raise StaleAction('Profile or writing preferences changed; regenerate draft')
    if t['platform']!='simulator':
        if not d['generator'].startswith('LLM-reviewed:'):raise PermissionError('Live replies require a reviewed model response')
        if automatic and not rt.auto_consent(t):raise PermissionError('Consent, disclosure and owner grant required')
    a=adapter(t);fresh=await a.snapshot(t);ingest(t,fresh)
    if not fresh or fresh[-1]['id']!=d['anchor_message_id']:
        s.set_draft_status(d['id'],'stale');rt.metric('stale_drafts');raise StaleAction('New message invalidates draft')
    if context[0].get('history_hash')!=rt.history_hash(s.messages(t['id'])):
        s.set_draft_status(d['id'],'stale');raise StaleAction('Conversation content changed; regenerate draft')
    # Snapshot await may allow an immediate revocation. Check again immediately before reserving send.
    t=thread_by_id(t['id'])
    if not t or not rt.eligible(t) or (automatic and not rt.auto_allowed(t)):raise PermissionError('Permission revoked')
    action='send-'+str(draft_id)+'-'+uuid4().hex
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM actions WHERE draft_id=?',(draft_id,)).fetchone():
            raise StaleAction('Action already attempted; reconcile first')
        if automatic:check_send_budget(db,t['id'])
        change=db.execute("UPDATE drafts SET status='sending' WHERE id=? AND status='pending' AND body=?",(draft_id,d['body']))
        if change.rowcount!=1:raise StaleAction('Draft rejected or changed during refresh')
        db.execute('INSERT INTO actions(id,draft_id,thread_id,anchor,status,receipt,updated,automatic) VALUES(?,?,?,?,?,?,?,?)',(action,draft_id,t['id'],d['anchor_message_id'],'sending',None,time.time(),int(automatic)))
    try:
        receipt=await asyncio.wait_for(a.send(t,d['body'],action,d['anchor_message_id']),timeout=20)
        if not receipt:raise RuntimeError('No verified receipt')
    except TinderRejected as exc:
        with s.connect() as db:db.execute("UPDATE actions SET status='rejected',updated=? WHERE id=?",(time.time(),action))
        s.set_draft_status(draft_id,'rejected');rt.audit(t['id'],'send_rejected',str(exc))
        return {'status':'rejected','reason':str(exc)}
    except DispatchDenied:
        with s.connect() as db:
            db.execute("UPDATE actions SET status='stale',updated=? WHERE id=?",(time.time(),action))
        s.set_draft_status(draft_id,'stale');raise
    except Exception as exc:
        with s.connect() as db:db.execute("UPDATE actions SET status='uncertain',updated=? WHERE id=?",(time.time(),action))
        s.set_draft_status(draft_id,'uncertain');rt.audit(t['id'],'send_uncertain','Delivery uncertain ('+type(exc).__name__+'); automatic resend blocked');rt.metric('failed_actions');return {'status':'uncertain'}
    complete(action,draft_id,receipt)
    try:ingest(t,s.source_for_thread(t['id']) if t['platform']=='tinder' else await a.snapshot(t))
    except Exception:rt.audit(t['id'],'post_send_sync_pending','Send verified; next synchronization will refresh the thread')
    return {'status':'sent','message_id':receipt}

def complete(action,draft,receipt):
    with s.connect() as db:
        db.execute("UPDATE actions SET status='sent',receipt=?,updated=? WHERE id=?",(receipt,time.time(),action))
        db.execute("UPDATE drafts SET status='sent' WHERE id=?",(draft,))
    rt.audit(None,'send_verified','Provider receipt recorded');rt.metric('messages_sent')

async def reconcile():
    for action in s.rows("SELECT * FROM actions WHERE status='uncertain'"):
        t=thread_by_id(action['thread_id'])
        if t:
            try:receipt=await adapter(t).reconcile(t,action['id'])
            except Exception:receipt=None
            if receipt:complete(action['id'],action['draft_id'],receipt);rt.metric('worker_recoveries')

async def run_jobs():
    """Draft generation, one job at a time. The lock is released between jobs, so the owner's clicks (send,
    new version) get in after at most one job instead of waiting for the whole queue."""
    for _ in range(50):
        if SHUTTING_DOWN:return
        async with LOCK:
            job=rt.claim()
            if not job:return
            try:await process_job(job)
            except (DispatchDenied,PermissionError,BudgetExceeded):rt.job_end(job,'blocked','Stale context or permission denied')
            except Exception:rt.job_end(job,'queued' if job['attempts']<4 else 'failed','Processing failed; inspect configuration');rt.metric('job_failures')
        await asyncio.sleep(0)

async def sync_once():
    async with SYNC:await sync_all()

async def housekeeping():
    from agent.notify import deliver_outbox
    await asyncio.to_thread(deliver_outbox)
    rt.expire();WORKER['last_tick']=s.utcnow();WORKER['error']=None

async def tick():
    """Everything once, in order: reconcile, synchronize, drafts. (The background worker runs these pieces apart.)"""
    if SHUTTING_DOWN or TICK.locked():return
    async with TICK:
        async with LOCK:await reconcile()
        await sync_once()
        await run_jobs()
        await housekeeping()

def _worker_failed(exc):
    import traceback
    frames=traceback.extract_tb(exc.__traceback__)
    rt.audit(None,'worker_error',type(exc).__name__+' at '+' > '.join(f.name+':'+str(f.lineno) for f in frames[-4:]))
    WORKER['error']='Synchronization failed ('+type(exc).__name__+'); check browser, credentials or source availability'
    rt.metric('sync_failures')

async def background_sync():
    try:await sync_once()
    except asyncio.CancelledError:raise
    except Exception as exc:_worker_failed(exc)
    finally:WAKE.set()  # new messages found: write their drafts now, not at the next interval

async def worker():
    """Drafts every few seconds; synchronization (which can take minutes during the first import) runs beside it,
    so a long import never stops drafts, sending or the owner's buttons."""
    WORKER['running']=True
    sync_task=None
    try:
        while True:
            try:
                if not SHUTTING_DOWN:
                    async with LOCK:await reconcile()
                    await run_jobs()
                    if sync_task is None or sync_task.done():sync_task=asyncio.create_task(background_sync())
                    await housekeeping()
            except asyncio.CancelledError:raise
            except Exception as exc:_worker_failed(exc)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(WAKE.wait(),float(os.getenv('WORKER_INTERVAL','5')))
            WAKE.clear()
    finally:
        if sync_task and not sync_task.done():sync_task.cancel()
        WORKER['running']=False
