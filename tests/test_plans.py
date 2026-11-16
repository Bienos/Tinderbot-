"""Plan limits (Winq / Flirt / Casanova): active conversations, queue, date-stage priority, autopilot gate."""
import json
from datetime import datetime,timedelta,timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from agent import storage as s,runtime as rt,service,plans

SECRET='test-dashboard-token-at-least-32-chars'


def make_thread(tid,*,platform='tinder',days_ago=0,sender='them',archived=0):
    ts=(datetime.now(timezone.utc)-timedelta(days=days_ago)).isoformat(timespec='seconds')
    with s.connect() as db:
        db.execute('INSERT OR REPLACE INTO threads(id,display_name,platform,connection_id,chat_id,source_seen,user_archived) VALUES(?,?,?,?,?,1,?)',(tid,tid,platform,'c1',tid,archived))
        db.execute('INSERT OR REPLACE INTO messages(id,thread_id,sender,body,created_at,synced_at) VALUES(?,?,?,?,?,?)',(tid+'-m',tid,sender,'hej',ts,ts))
    return service.thread_by_id(tid)


def test_without_a_plan_nothing_is_limited(store,monkeypatch):
    monkeypatch.delenv('PLAN',raising=False)
    assert plans.status() is None and plans.autopilot_allowed() and all(plans.admit(make_thread(f't{i}')) for i in range(50))


def test_wink_admits_three_conversations_and_queues_the_rest(store,monkeypatch):
    monkeypatch.setenv('PLAN','winq')
    ts=[make_thread(f't{i}') for i in range(5)]
    assert [plans.admit(t) for t in ts]==[True,True,True,False,False]
    assert plans.admit(ts[0]) is True                      # a conversation keeps its slot
    st=plans.status(service.s.threads(),s.messages_by_thread())
    assert st['label']=='Winq' and st['limit']==3 and st['used']==3 and st['autopilot'] is False and st['queued']==['t3','t4']


def test_slot_frees_when_a_conversation_goes_cold_or_is_archived(store,monkeypatch):
    monkeypatch.setenv('PLAN','winq')
    ts=[make_thread(f't{i}') for i in range(4)]
    assert [plans.admit(t) for t in ts]==[True,True,True,False]
    make_thread('t0',days_ago=plans.ACTIVE_DAYS+2)          # silent for two weeks: not active any more
    assert plans.admit(ts[3]) is True
    s.set_thread_flags('t1',archived=True)
    assert plans.admit(make_thread('t5')) is True           # archived conversation freed another slot
    assert plans.admit(make_thread('t6')) is False


def test_date_stage_conversations_are_never_blocked(store,monkeypatch):
    monkeypatch.setenv('PLAN','winq')
    for i in range(3):assert plans.admit(make_thread(f't{i}'))
    date=make_thread('hot')
    assert plans.admit(date) is False
    rt.record_outcomes('hot','hot-m',[type('O',(),{'kind':'date_tentative','fingerprint':'f','body':'b','as_dict':lambda self:{'kind':'date_tentative'}})()])
    assert plans.admit(date) is True and plans.admit(make_thread('late')) is False


def test_simulator_and_plan_override(store,monkeypatch):
    monkeypatch.setenv('PLAN','winq');monkeypatch.setenv('PLAN_CONVERSATIONS','1')
    assert plans.admit(make_thread('t0')) and not plans.admit(make_thread('t1'))
    assert plans.admit(make_thread('sim',platform='simulator'))
    monkeypatch.setenv('PLAN','casanova');monkeypatch.delenv('PLAN_CONVERSATIONS')
    assert plans.limit()==30 and plans.autopilot_allowed()


def test_waiting_conversations_get_a_draft_when_a_slot_opens(store,monkeypatch):
    monkeypatch.setenv('PLAN','winq');monkeypatch.setattr(rt,'eligible',lambda t,ctx=None:not t['user_archived'])
    for i in range(4):make_thread(f't{i}')
    assert service.promote_waiting(force=True)==3
    queued=lambda:{r['thread_id'] for r in s.rows('SELECT thread_id FROM jobs')}
    assert queued()=={'t0','t1','t2'}
    s.set_thread_flags('t0',archived=True)
    assert service.promote_waiting(force=True)==3 and 't3' in queued()


async def test_autopilot_is_refused_below_flirt(store,monkeypatch):
    from agent import tinder
    from app import app
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN','fake')
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient('fake',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'data':{'_id':'owner'} if r.url.path=='/profile' else {'matches':[]}}))))
    cid=await tinder.connect();tid=cid+':match'
    with s.connect() as db:
        db.execute('INSERT INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1)',(tid,'Test','tinder',cid,'match'))
        db.execute('INSERT INTO grants VALUES(?,?,?,?)',(tid,1,1,1))
    monkeypatch.setenv('PLAN','winq')
    assert not rt.auto_allowed(service.thread_by_id(tid))                  # drafts only, even for an already enabled account
    with TestClient(app,headers={'Authorization':'Bearer '+SECRET}) as c:
        r=c.put('/api/tinder/connections/'+cid+'/automation',json={'enabled':True})
        assert r.status_code==403 and 'Flirt' in r.json()['detail']
        state=c.get('/api/state').json()
        assert state['plan']['label']=='Winq' and state['plan']['limit']==3
        monkeypatch.setenv('PLAN','flirt')
        assert c.put('/api/tinder/connections/'+cid+'/automation',json={'enabled':True}).status_code==200
        assert rt.auto_allowed(service.thread_by_id(tid))
        monkeypatch.delenv('PLAN');assert c.get('/api/state').json()['plan'] is None


def test_only_casanova_has_advanced_stats(store,monkeypatch):
    got={}
    for name in ('winq','flirt','casanova'):
        monkeypatch.setenv('PLAN',name);got[name]=plans.status()['advanced_stats']
    assert got=={'winq':False,'flirt':False,'casanova':True}
