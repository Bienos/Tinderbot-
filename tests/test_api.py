"""Run the full orchestration without Chrome or any real dating platform."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def test_local_fixture_inbox_flow():
    with tempfile.TemporaryDirectory() as temp:
        script = r'''
import os
from fastapi.testclient import TestClient
from app import app
from agent import storage
with TestClient(app, headers={'Authorization':'Bearer '+os.environ['DASHBOARD_TOKEN']}) as c:
  r=c.get('/api/state'); assert r.status_code==200
  states={t['id']:t['state'] for t in r.json()['threads']}
  assert len(states)==7, states
  assert states['t4']=='not_synced', states
  assert all(v=='not_synced' for v in states.values()), 'Before first sync do not guess conversation state'
  r=c.post('/api/sync'); assert r.status_code==200, r.text
  states={t['id']:t['state'] for t in c.get('/api/state').json()['threads']}
  assert states['t4']=='new_match', states
  assert states['t5']=='waiting', states
  assert states['t6']=='needs_reply', states
  assert r.json()['new_verified_notifications']==2
  r2=c.post('/api/sync'); assert r2.status_code==200
  assert r2.json()['new_verified_notifications']==0
  assert r2.json()['drafts_created']==0
  state=c.get('/api/state').json()
  assert 'instagram_shared' in next(t for t in state['threads'] if t['id']=='t2')['outcomes']
  assert 'date_confirmed' in next(t for t in state['threads'] if t['id']=='t3')['outcomes']
  d=next(d for d in state['drafts'] if d['thread_id']=='t1')
  assert c.post('/api/drafts/%s/approve'%d['id']).status_code==200
  assert c.post('/api/sync').status_code==200
  assert next(t for t in c.get('/api/state').json()['threads'] if t['id']=='t1')['state']=='waiting'
  assert c.post('/api/threads/t6/flags',json={'paused':True}).status_code==200
  assert next(t for t in c.get('/api/state').json()['threads'] if t['id']=='t6')['state']=='paused'
  storage.set_thread_flags('t5', visibility='not_observed')
  assert next(t for t in c.get('/api/state').json()['threads'] if t['id']=='t5')['state']=='unavailable_unknown'
  assert c.post('/api/mock/threads/t5/simulate-visibility?visible=true').status_code==200
  assert next(t for t in c.get('/api/state').json()['threads'] if t['id']=='t5')['state']=='waiting'
'''
        env={**os.environ,'AGENT_DB_PATH':str(Path(temp)/'test.db'),'DATING_AGENT_SOURCE':'fixture','WORKER_ENABLED':'false','PUBLIC_ORIGIN':'http://testserver','DASHBOARD_TOKEN':'test-dashboard-token-at-least-32-chars','SEED_SIMULATOR':'true','COOKIE_SECURE':'false'}
        env.pop('OPENAI_API_KEY',None)
        env.pop('ANTHROPIC_API_KEY',None)
        env['TINDER_ENABLED']='false';env.pop('TINDER_AUTH_TOKEN',None)
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,env=env,timeout=30)
        assert result.returncode==0, result.stdout+'\n'+result.stderr


def test_state_survives_threads_added_during_request(store,monkeypatch):
    """A running Tinder sync adds threads between queries; /api/state must use one consistent snapshot."""
    import app as application
    from agent import storage as s
    real=s.threads;calls={'n':0}
    def racing():
        calls['n']+=1;rows=real()
        if calls['n']>1:rows=rows+[{**rows[0],'id':'late-thread','display_name':'Late'}]
        return rows
    monkeypatch.setattr(s,'threads',racing)
    assert application.state()['threads']


def test_stale_lease_never_blocks_startup_but_a_live_second_worker_does():
    import os,time
    from app import lease_blocks
    me=f'host-new:{os.getpid()}:aa'
    soon=time.time()+100
    assert not lease_blocks(None,me)
    assert not lease_blocks({'owner':'host-old:40:bb','expires':soon},me)               # restarted container
    assert not lease_blocks({'owner':f'host-new:{os.getpid()}:old','expires':soon},me)  # earlier process, same pid, gone
    assert not lease_blocks({'owner':'host-new:999999:cc','expires':soon},me)           # same container, process is dead
    assert lease_blocks({'owner':f'host-new:{os.getppid()}:cc','expires':soon},me)      # a live second worker here
    assert not lease_blocks({'owner':f'host-new:{os.getppid()}:cc','expires':time.time()-1},me)  # expired


async def test_sigterm_releases_the_lease_and_stops_background_work(store):
    import os,signal
    import app as application
    from agent import service
    previous=signal.getsignal(signal.SIGTERM);signal.signal(signal.SIGTERM,lambda *a:None)
    try:
        async with application.lifespan(application.app):
            assert store.rows("SELECT * FROM leases WHERE name='coordinator'")
            os.kill(os.getpid(),signal.SIGTERM)  # the handler frees the lease before anything slow can happen
            assert not store.rows("SELECT * FROM leases WHERE name='coordinator'")
            assert service.SHUTTING_DOWN
    finally:signal.signal(signal.SIGTERM,previous);service.SHUTTING_DOWN=False
