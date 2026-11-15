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
        env={**os.environ,'AGENT_DB_PATH':str(Path(temp)/'test.db'),'DATING_AGENT_SOURCE':'fixture','WORKER_ENABLED':'false','PUBLIC_ORIGIN':'http://testserver','DASHBOARD_TOKEN':'test-dashboard-token-at-least-32-chars'}
        env.pop('OPENAI_API_KEY',None)
        env['TINDER_ENABLED']='false';env.pop('TINDER_AUTH_TOKEN',None)
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,env=env,timeout=30)
        assert result.returncode==0, result.stdout+'\n'+result.stderr
