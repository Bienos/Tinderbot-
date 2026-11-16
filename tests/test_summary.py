"""The bot's /internal/summary: aggregate numbers for the weekly e-mail and the fleet check. Counts only, signed requests only."""
import json,time
from datetime import datetime,timezone
import pytest
from fastapi.testclient import TestClient
from agent import storage as s,runtime as rt

SSO='s'*40
H=3600

def iso(ts):return datetime.fromtimestamp(ts,timezone.utc).isoformat(timespec='seconds')

def add_thread(tid,name,matched_ago,msgs,now):
    """msgs: [(sender, hours ago)] in any order."""
    with s.connect() as db:
        db.execute('INSERT INTO threads (id,display_name) VALUES (?,?)',(tid,name))
        db.execute('INSERT INTO tinder_threads VALUES (?,?)',(tid,json.dumps({'profile':{'matched_at':iso(now-matched_ago*H),'age':27}})))
    for i,(sender,ago) in enumerate(msgs):
        s.sync_message({'id':f'{tid}-{i}','thread_id':tid,'sender':sender,'body':'SECRET BODY '+tid,'created_at':iso(now-ago*H)})

@pytest.fixture
def filled(store):
    now=time.time()
    with s.connect() as db:db.execute('DELETE FROM threads')
    add_thread('a','Agata-private',48,[('you',40),('them',39),('you',30),('them',29)],now)      # two answered runs, waiting for us
    add_thread('c','Celina-private',24,[('you',20)],now)                                         # asked >6 h ago, no answer
    add_thread('d','Dorota-private',3,[('you',1)],now)                                           # too fresh to count
    add_thread('old','Olga-private',10*24,[('you',9*24)],now)                                    # previous week
    for k in range(5):add_thread(f'x{k}',f'Xena{k}-private',30,[('you',25),('them',24)],now)     # five more answered runs
    s.new_notification('a','date_confirmed','fp1','b');s.new_notification('x0','instagram_shared','fp2','b')
    with s.connect() as db:
        db.execute("INSERT INTO actions VALUES ('act1',1,'a','m','sent',NULL,?,1)",(now-5*H,))
        db.execute("INSERT INTO connections VALUES ('tinder:u',1,1,'u',?)",(json.dumps({'error':None,'last_sync':s.utcnow()}),))
    return now

def test_weekly_counts_and_rates(filled):
    from agent import summary
    d=summary.weekly(filled)
    t,p=d['this'],d['prev']
    assert t['matches']==8 and p['matches']==1                      # a,c,d + five x; old was matched 10 days ago
    assert t['messages_you']==9 and t['messages_them']==7
    assert t['asked']==8 and t['answered']==7 and t['reply_rate']==88   # d is too fresh to count
    assert p['asked']==1 and p['reply_rate'] is None                # fewer than 5 asked: no percentage
    assert t['meetings']==1 and t['contacts']==1 and t['sent_by_agent']==1
    assert d['now']['needs_reply']==6 and d['now']['conversations']==9   # a, c, d, old and five x have messages; a and the five x end with hers

def test_summary_holds_no_names_or_message_text(filled):
    from agent import summary
    blob=json.dumps(summary.weekly(filled))
    assert 'private' not in blob and 'SECRET' not in blob and 'Agata' not in blob

def test_health_codes(filled,monkeypatch):
    from agent import summary
    assert summary.weekly(filled)['health']['status']=='ok' and summary.weekly(filled)['health']['tinder']['connected']
    with s.connect() as db:db.execute("UPDATE connections SET value=?",(json.dumps({'error':'session_expired_or_account_changed','last_sync':s.utcnow()}),))
    h=summary.weekly(filled)['health']
    assert h['status']=='problem' and 'tinder_error:session_expired_or_account_changed' in h['issues'] and not h['tinder']['connected']
    with s.connect() as db:db.execute("UPDATE connections SET enabled=1,value=?",(json.dumps({'error':None,'last_sync':iso(filled-9*H)}),))
    assert 'sync_stale' in summary.weekly(filled)['health']['issues']
    with s.connect() as db:db.execute('DELETE FROM connections')
    assert 'tinder_not_connected' in summary.weekly(filled)['health']['issues']
    cfg=rt.settings();rt.save_settings({**cfg,'paused':True})
    h=summary.weekly(filled)['health'];assert 'agent_paused' in h['issues'] and h['agent']['paused']

def signed(secret,audience='http://testserver',offset=0):
    from control.weekly import signed_headers
    return signed_headers(secret,audience,now=time.time()+offset)

def test_endpoint_requires_a_signature_from_the_control_service(filled,monkeypatch):
    from app import app
    monkeypatch.setenv('PUBLIC_ORIGIN','http://testserver');monkeypatch.setenv('SSO_SECRET',SSO)
    with TestClient(app) as c:                                       # no dashboard token and no cookie: only the signature counts
        assert c.get('/internal/summary').status_code==401
        assert c.get('/internal/summary',headers=signed('x'*40)).status_code==401                       # wrong secret
        assert c.get('/internal/summary',headers=signed(SSO,audience='https://other.example')).status_code==401   # another bot's signature
        assert c.get('/internal/summary',headers=signed(SSO,offset=-600)).status_code==401              # stale
        r=c.get('/internal/summary?days=7',headers=signed(SSO));assert r.status_code==200
        body=r.json();assert body['version']==1 and body['this']['matches']==8 and 'private' not in r.text
        monkeypatch.setenv('SSO_SECRET','');assert c.get('/internal/summary',headers=signed(SSO)).status_code==401   # not linked to an account: closed

def test_sso_next_stats_opens_the_statistics_tab(store,monkeypatch):
    import base64,hashlib,hmac
    from app import app
    monkeypatch.setenv('PUBLIC_ORIGIN','http://testserver');monkeypatch.setenv('SSO_SECRET',SSO)
    def token():
        payload=base64.urlsafe_b64encode(json.dumps({'aud':'http://testserver','sub':'a@b.pl','exp':int(time.time())+60,'n':__import__('secrets').token_urlsafe(16)}).encode()).decode().rstrip('=')
        return payload+'.'+base64.urlsafe_b64encode(hmac.new(SSO.encode(),payload.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    with TestClient(app) as c:
        assert 'url=/#stats"' in c.get('/auth/sso',params={'t':token(),'next':'stats'}).text
        assert 'url=/"' in c.get('/auth/sso',params={'t':token(),'next':'https://evil.example'}).text   # only a known view is accepted

@pytest.mark.parametrize('plan,advanced',[('winq',False),('flirt',False),('casanova',True),('',True)])
def test_summary_reports_whether_the_plan_has_advanced_statistics(filled,monkeypatch,plan,advanced):
    from agent import summary
    monkeypatch.setenv('PLAN',plan)                                   # no plan (the owner's own bot): nothing is limited
    d=summary.weekly(filled)['plan'];assert d['advanced_stats'] is advanced and d['name']==(plan or None)


def test_health_counts_conversations_that_could_not_be_read(store):
    import json
    from agent import summary
    with s.connect() as db:
        db.execute("INSERT INTO tinder_threads VALUES('a',?),('b',?),('c',?)",
                   (json.dumps({'read_failed': True}), json.dumps({'person_id': 'x'}), json.dumps({'read_failed': True, 'failed_at': 1})))
    assert summary.weekly()['health']['tinder']['unreadable_threads'] == 2
