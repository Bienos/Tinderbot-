"""Security regressions. All external providers are mocked; only TestClient uses local sockets."""
import json,os,ssl,time
import httpx,pytest
from fastapi.testclient import TestClient
from agent import auth,storage as s,runtime as rt,service
from agent.adapters import FixtureAdapter,StaleAction,TelegramAdapter
from agent.dispatch import DispatchDenied
SECRET='test-dashboard-token-at-least-32-chars'

def test_empty_token_file_fails_closed(store,monkeypatch):
    monkeypatch.delenv('DASHBOARD_TOKEN');(s.DB_PATH.parent/'dashboard-token').write_text('')
    with pytest.raises(RuntimeError):auth.token()

def test_token_file_symlink_is_rejected(store,monkeypatch):
    monkeypatch.delenv('DASHBOARD_TOKEN')
    target=s.DB_PATH.parent/'other';target.write_text(SECRET)
    (s.DB_PATH.parent/'dashboard-token').symlink_to(target)
    with pytest.raises(RuntimeError):auth.token()

def test_cookie_not_master_credential_and_logout_invalidates_replay(store,monkeypatch):
    from app import app
    monkeypatch.setenv('PUBLIC_ORIGIN','http://testserver')
    with TestClient(app) as c:
        r=c.post('/auth/login',json={'token':SECRET});assert r.status_code==200
        cookie=r.cookies['agent_session'];assert cookie!=SECRET
        assert c.get('/api/state').status_code==200
        assert c.post('/auth/logout',headers={'X-Agent-Request':'dashboard'}).status_code==200
        c.cookies.set('agent_session',cookie)
        assert c.get('/api/state').status_code==401

def test_host_header_rebinding_is_rejected_even_with_valid_bearer(store):
    from app import app
    with TestClient(app,headers={'Authorization':'Bearer '+SECRET}) as c:
        assert c.get('/api/state',headers={'Host':'evil.example'}).status_code==400

def test_unauthenticated_oversize_body_and_chunked_body_rejected(store):
    from app import app
    with TestClient(app) as c:
        assert c.post('/auth/login',content=b'x'*70000,headers={'Content-Type':'application/json'}).status_code==413
        assert c.post('/auth/login',content=iter([b'x'*35000,b'x'*35000]),headers={'Content-Type':'application/json'}).status_code==413

def test_login_page_has_security_headers_and_no_inline_script_permission(store):
    from app import app
    with TestClient(app) as c:
        r=c.get('/');assert r.status_code==401
        assert r.headers.get('Cache-Control')=='no-store'
        assert "script-src 'self';" in r.headers.get('Content-Security-Policy','')
        assert "script-src 'self' 'unsafe-inline'" not in r.headers.get('Content-Security-Policy','')

async def test_rejection_during_source_refresh_cannot_be_sent(store,monkeypatch):
    await service.sync_all()
    while (job:=rt.claim()):await service.process_job(job)
    d=next(d for d in s.all_drafts() if d['thread_id']=='t1')
    class Reject(FixtureAdapter):
        async def snapshot(self,t):s.set_draft_status(d['id'],'rejected');return await super().snapshot(t)
    monkeypatch.setattr(service,'adapter',lambda t:Reject())
    before=len(s.source_for_thread('t1'))
    with pytest.raises(StaleAction):await service.execute(d['id'])
    assert len(s.source_for_thread('t1'))==before

@pytest.mark.parametrize('revocation',['grant','pause','mode','history','profile','draft'])
async def test_telegram_grant_revoked_after_reservation_prevents_dispatch(store,monkeypatch,revocation):
    import agent.adapters as adapters
    thread='tg:con:999';item={'id':thread+':7','thread_id':thread,'sender':'them','body':'hello','created_at':s.utcnow()}
    with s.connect() as db:
        db.execute('INSERT INTO connections VALUES(?,?,?,?,?)',('con',1,1,'123','{}'))
        db.execute('INSERT INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1)',(thread,'Test','telegram','con','999'))
        db.execute('INSERT INTO source_messages VALUES(?,?,?,?,?)',tuple(item[k] for k in ('id','thread_id','sender','body','created_at')))
        db.execute('INSERT INTO grants VALUES(?,?,?,?)',(thread,1,1,1))
    s.sync_message(item);s.upsert_draft(thread,item['id'],'reply','LLM-reviewed:test');d=s.all_drafts()[0]
    cfg=rt.settings();cfg['mode']='authorized_autonomy';rt.save_settings(cfg)
    with s.connect() as db:
        db.execute('INSERT INTO draft_context VALUES(?,?,?)',(d['id'],rt.settings_hash(),rt.history_hash([item])))
        db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)',('action',d['id'],thread,item['id'],'sending',None,time.time(),1))
        db.execute("UPDATE drafts SET status='sending' WHERE id=?",(d['id'],))
    if revocation=='grant':
        with s.connect() as db:db.execute('UPDATE grants SET enabled=0 WHERE thread_id=?',(thread,))
    elif revocation=='pause':
        cfg=rt.settings();cfg['paused']=True;rt.save_settings(cfg)
    elif revocation=='mode':
        cfg=rt.settings();cfg['mode']='supervised';rt.save_settings(cfg)
    elif revocation=='history':
        with s.connect() as db:db.execute("UPDATE source_messages SET body='edited' WHERE thread_id=?",(thread,))
    elif revocation=='profile':
        cfg=rt.settings();cfg['profile']={'city':'Changed'};rt.save_settings(cfg)
    elif revocation=='draft':s.set_draft_status(d['id'],'rejected')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','fake')
    calls=[]
    def handler(req):calls.append(req);return httpx.Response(200,json={'ok':True,'result':{'message_id':8,'chat':{'id':999}}})
    client=httpx.AsyncClient;monkeypatch.setattr(adapters.httpx,'AsyncClient',lambda **kw:client(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises((DispatchDenied,PermissionError)):await TelegramAdapter().send(service.thread_by_id(thread),'reply','action',item['id'])
    assert not calls

def test_smtp_requires_verified_tls_context(store,monkeypatch):
    from agent import notify
    cfg=rt.settings();cfg['email']=True;rt.save_settings(cfg)
    for k,v in {'SMTP_HOST':'smtp.example','NOTIFY_TO':'owner@example','NOTIFY_FROM':'agent@example'}.items():monkeypatch.setenv(k,v)
    contexts=[]
    class SMTP:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def starttls(self,context=None):contexts.append(context)
        def send_message(self,*a):pass
    monkeypatch.setattr(notify.smtplib,'SMTP',SMTP)
    notify.maybe_email('date_confirmed','','',1)
    assert contexts[0] is not None and contexts[0].verify_mode==ssl.CERT_REQUIRED and contexts[0].check_hostname

async def test_connecting_tinder_does_not_escalate_telegram_autonomy(store,monkeypatch):
    from agent import tinder
    tid='tg:con:999'
    with s.connect() as db:
        db.execute('INSERT INTO connections VALUES(?,?,?,?,?)',('con',1,1,'123','{}'))
        db.execute('INSERT INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1)',(tid,'Test','telegram','con','999'))
        db.execute('INSERT INTO grants VALUES(?,?,?,?)',(tid,1,1,1))
    assert not rt.auto_allowed(service.thread_by_id(tid))
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN','fake')
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient('fake',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'data':{'_id':'owner'}}))))
    await tinder.connect()
    assert not rt.auto_allowed(service.thread_by_id(tid))

def test_server_side_session_expiry_and_token_rotation(store,monkeypatch):
    from app import app
    with TestClient(app) as c:
        cookie=c.post('/auth/login',json={'token':SECRET}).cookies['agent_session']
        assert cookie!=SECRET
        with s.connect() as db:db.execute('UPDATE sessions SET expires=?',(time.time()-1,))
        assert c.get('/api/state').status_code==401
        cookie=c.post('/auth/login',json={'token':SECRET}).cookies['agent_session']
        monkeypatch.setenv('DASHBOARD_TOKEN','rotated-test-token-at-least-32-characters')
        assert c.get('/api/state').status_code==401
        assert cookie not in json.dumps(s.rows('SELECT * FROM sessions'))

def test_unicode_credentials_do_not_raise_internal_error(store):
    from app import app
    with TestClient(app) as c:
        assert c.post('/auth/login',json={'token':'ż'*30}).status_code==401
        assert c.get('/api/state',headers={'Authorization':'Bearer invalid'}).status_code==401

def test_model_input_and_call_budget_prevents_remote_cost_exhaustion(store,monkeypatch):
    from agent.engine import structured,Decision
    from agent.limits import claim_model_call,BudgetExceeded
    with pytest.raises(BudgetExceeded):structured('test',{'text':'x'*70000},Decision)
    assert not s.rows('SELECT * FROM model_calls')
    monkeypatch.setenv('MODEL_CALLS_PER_MINUTE','2')
    claim_model_call();claim_model_call()
    with pytest.raises(BudgetExceeded):claim_model_call()
    assert len(s.rows('SELECT * FROM model_calls'))==2

async def test_autosend_budget_blocks_new_dispatch_without_turn_approval(store,monkeypatch):
    from agent.limits import BudgetExceeded
    await service.sync_all()
    while (job:=rt.claim()):await service.process_job(job)
    d=next(d for d in s.all_drafts() if d['thread_id']=='t1')
    cfg=rt.settings();cfg['mode']='simulation';rt.save_settings(cfg)
    monkeypatch.setenv('AUTO_SENDS_PER_THREAD_HOUR','1')
    with s.connect() as db:db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)',('prior',-1,'t1','older','sent','receipt',time.time(),1))
    before=len(s.source_for_thread('t1'))
    with pytest.raises(BudgetExceeded):await service.execute(d['id'],automatic=True)
    assert len(s.source_for_thread('t1'))==before and s.draft_by_id(d['id'])['status']=='pending'

async def test_no_external_generation_before_telegram_consent(store,monkeypatch):
    tid='tg:con:999'
    with s.connect() as db:
        db.execute('INSERT INTO connections VALUES(?,?,?,?,?)',('con',1,1,'123','{}'))
        db.execute('INSERT INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1)',(tid,'Test','telegram','con','999'))
    assert not rt.eligible(service.thread_by_id(tid))
    with s.connect() as db:db.execute('INSERT INTO grants VALUES(?,?,?,?)',(tid,1,1,1))
    assert rt.eligible(service.thread_by_id(tid))

def test_public_static_script_and_protected_dashboard_assets(store):
    from app import app
    with TestClient(app) as c:
        assert c.get('/static/login.js').status_code==200
        assert c.get('/static/dashboard.js').status_code==401
        c.headers['Authorization']='Bearer '+SECRET
        assert c.get('/static/dashboard.js').status_code==200
        assert c.get('/static/private.js').status_code==404
        assert c.post('/api/settings',headers={'Origin':'https://evil.example'},json={}).status_code==403

async def test_tinder_automatic_sending_remains_on_and_is_independently_revocable(store,monkeypatch):
    from agent import tinder
    from app import app
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN','fake')
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient('fake',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'data':{'_id':'owner'}}))))
    cid=await tinder.connect();tid=cid+':match'
    with s.connect() as db:
        db.execute('INSERT INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1)',(tid,'Test','tinder',cid,'match'))
        db.execute('INSERT INTO grants VALUES(?,?,?,?)',(tid,1,1,1))
    assert rt.settings()['mode']=='supervised' and rt.auto_allowed(service.thread_by_id(tid))
    assert tinder.public_status()['connections'][0]['auto_send'] is True
    with TestClient(app,headers={'Authorization':'Bearer '+SECRET}) as c:
        r=c.put('/api/tinder/connections/'+cid+'/automation',json={'enabled':False});assert r.status_code==200
        assert not rt.auto_allowed(service.thread_by_id(tid))
        assert c.put('/api/tinder/connections/'+cid+'/automation',json={'enabled':True}).status_code==200
        assert rt.auto_allowed(service.thread_by_id(tid))
        cfg=rt.settings();cfg['mode']='simulation';rt.save_settings(cfg)
        assert not rt.auto_allowed(service.thread_by_id(tid))

def test_private_browser_and_healthcheck_work_behind_public_tls_origin(store,monkeypatch):
    from app import app
    monkeypatch.setenv('PUBLIC_ORIGIN','https://agent.example')
    with TestClient(app,base_url='http://127.0.0.1:8765',client=('127.0.0.1',12345)) as c:
        assert c.get('/health').status_code==200
        assert c.get('/api/state').status_code==400
        c.headers['Authorization']='Bearer '+SECRET
        assert c.get('/api/state').status_code==200
        assert c.post('/api/threads/t1/flags',json={'paused':True},headers={'Origin':'http://127.0.0.1:8765'}).status_code==200
        assert c.post('/api/threads/t1/flags',json={'paused':False},headers={'Origin':'https://evil.example'}).status_code==403
