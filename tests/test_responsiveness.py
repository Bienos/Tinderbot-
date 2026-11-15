"""The panel must stay usable while the bot works: a long import or an LLM queue must not freeze buttons."""
import asyncio
import pytest
from agent import storage as s,runtime as rt,service


async def ingest_and_draft(store):
    await service.sync_all()
    job=rt.claim()
    while job:
        await service.process_job(job);job=rt.claim()
    return next(d for d in s.all_drafts() if d['thread_id']=='t1' and d['status']=='pending')


async def test_new_draft_and_send_are_not_blocked_by_a_long_sync(store):
    import app as application
    d=await ingest_and_draft(store)
    release=asyncio.Event()
    async def long_import():
        async with service.SYNC:await release.wait()   # a first import that takes minutes
    task=asyncio.create_task(long_import());await asyncio.sleep(0)
    assert service.SYNC.locked()
    try:
        assert await asyncio.wait_for(application.regenerate('t1'),2)=={'ok':True}
        assert s.draft_by_id(d['id'])['status']=='regenerate'
        assert s.rows("SELECT updated FROM jobs WHERE thread_id='t1'")[0]['updated']==0  # owner request goes first
    finally:
        release.set();await task


async def test_manual_sync_says_busy_instead_of_hanging(store):
    import app as application
    from fastapi import HTTPException
    async with service.SYNC:
        with pytest.raises(HTTPException) as e:await application.tinder_sync()
        assert e.value.status_code==409


async def test_owner_click_waits_for_the_job_in_progress_but_not_forever(store):
    async def hold():
        async with service.LOCK:await asyncio.sleep(0.3)
    task=asyncio.create_task(hold());await asyncio.sleep(0)
    async with service.owner_lock(wait=2):pass               # short job: the click goes through
    await task
    async with service.LOCK:
        with pytest.raises(service.Busy):
            async with service.owner_lock(wait=0.05):pass     # stuck job: a clear "busy", not a hang


async def test_worker_keeps_writing_drafts_while_a_sync_is_running(store,monkeypatch):
    await service.sync_all()                                   # messages in, jobs queued
    started=asyncio.Event();release=asyncio.Event()
    async def endless_import():
        started.set();await release.wait()
    monkeypatch.setattr(service,'sync_all',endless_import)
    monkeypatch.setenv('WORKER_INTERVAL','0.05')
    worker=asyncio.create_task(service.worker())
    try:
        await asyncio.wait_for(started.wait(),2)
        for _ in range(100):
            if any(d['thread_id']=='t1' for d in s.all_drafts()):break
            await asyncio.sleep(0.05)
        assert any(d['thread_id']=='t1' for d in s.all_drafts()), 'no draft written while the sync was running'
        assert service.SYNC.locked()                           # the import really was still "running"
    finally:
        release.set();worker.cancel()
        with pytest.raises(asyncio.CancelledError):await worker
        assert not service.WORKER['running']


async def test_changing_style_rewrites_waiting_drafts_instead_of_leaving_them_outdated(store):
    import app as application
    d=await ingest_and_draft(store)
    cfg=rt.settings()
    r=await application.settings(application.Settings(**{**cfg,'style':'krótko, z humorem, od wielkiej litery'}))
    assert r['regenerating']>=1
    assert s.draft_by_id(d['id'])['status']=='regenerate'
    job=rt.claim();assert job and job['thread_id']=='t1'
    await service.process_job(job)
    fresh=s.draft_by_id(d['id']);assert fresh['status']=='pending'
    ctx=s.rows('SELECT settings_hash FROM draft_context WHERE draft_id=?',(d['id'],))[0]['settings_hash']
    assert ctx==rt.settings_hash()                             # written with the new style, so it can be sent
    same=await application.settings(application.Settings(**rt.settings()))
    assert same['regenerating']==0                             # saving without changes touches nothing


def test_prompt_tells_the_model_to_follow_the_owners_style_setting():
    from agent.engine import SYSTEM_PROMPT
    assert 'preferences.style' in SYSTEM_PROMPT and 'preferences.feedback' in SYSTEM_PROMPT


async def test_listing_shortcuts_give_exactly_the_same_answers_as_the_per_thread_queries(store):
    import json
    await ingest_and_draft(store)
    with s.connect() as db:  # a live Tinder-style connection with the autopilot on, so every branch is exercised
        db.execute("INSERT OR REPLACE INTO connections(id,enabled,can_reply,user_id,value) VALUES('tinder:o',1,1,'o',?)",
                   (json.dumps({'auto_send':True,'bio_mode':True,'bio_disclosure':True}),))
        db.execute("INSERT OR REPLACE INTO grants VALUES('t2',0,0,0)")
    by_thread=s.messages_by_thread()
    assert by_thread=={t['id']:s.messages(t['id']) for t in s.threads() if s.messages(t['id'])}
    mem=rt.memory_by_thread()
    assert mem=={t['id']:rt.memory(t['id']) for t in s.threads() if rt.memory(t['id'])}
    ctx={'cfg':rt.settings(),'hist':{t['id']:by_thread.get(t['id'],[]) for t in s.threads()},
         'grants':{g['thread_id']:g for g in s.rows('SELECT * FROM grants')}}
    for t in s.threads():
        assert rt.eligible(t,ctx)==rt.eligible(t),t['id']
        assert rt.auto_allowed(t,ctx)==rt.auto_allowed(t),t['id']
        assert rt.auto_consent(t,ctx)==rt.auto_consent(t),t['id']


def test_state_with_hundreds_of_matches_stays_fast(store):
    import json,time
    import app as application
    with s.connect() as db:
        for i in range(300):
            tid=f'tinder:o:m{i}'
            db.execute('INSERT INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1)',(tid,f'Osoba {i}','tinder','tinder:o',f'm{i}'))
            for j in range(20):
                db.execute('INSERT INTO messages (id,thread_id,sender,body,created_at,synced_at) VALUES (?,?,?,?,?,?)',
                           (f'{tid}:{j}',tid,'them' if j%2==0 else 'you','a ty co robisz w weekend?',f'2026-11-{1+j//4:02d}T10:{j:02d}:00+00:00',s.utcnow()))
    application.state()
    t0=time.perf_counter();r=application.state();took=time.perf_counter()-t0
    assert len(r['threads'])>=300 and took<1.5,f'state() took {took:.2f}s'   # was ~5x slower before the shortcuts
