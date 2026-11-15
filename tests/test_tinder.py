"""OpenDate-derived connector contracts and application orchestration. All HTTP is mocked."""
import json
import gzip,zlib
from datetime import datetime,timezone,timedelta
import httpx
import pytest
from agent import tinder,storage as s,runtime as rt,service
from agent.adapters import adapter,StaleAction
from agent.engine import Decision
OWNER='owner-a';PERSON='person-a';CID='tinder:owner-a';TID='tinder:owner-a:match-a'
TOKEN='fake-private-token-for-offline-tests'

@pytest.mark.parametrize('encoding,compress',[('gzip',gzip.compress),('deflate',zlib.compress)])
async def test_compressed_profile_response_is_decoded_once(store,encoding,compress):
    body=compress(json.dumps({'data':{'_id':OWNER}}).encode())
    def handle(req):
        return httpx.Response(200,headers={'Content-Type':'application/json','Content-Encoding':encoding},content=body)
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)) as api:
        assert await api.profile()==OWNER

@pytest.mark.parametrize('status,expected',[(401,tinder.TinderAuthError),(403,tinder.TinderRestriction),
    (429,tinder.TinderRateLimited),(503,tinder.TinderRateLimited)])
async def test_compressed_error_response_preserves_status_and_retry_after(store,status,expected):
    body=gzip.compress(json.dumps({'error':'synthetic-upstream-error'}).encode())
    calls=[]
    def handle(req):
        calls.append(req)
        return httpx.Response(status,headers={'Content-Type':'application/json','Content-Encoding':'gzip',
            'Retry-After':'180'},content=body)
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)) as api:
        with pytest.raises(expected) as error:await api.profile()
    assert len(calls)==1
    if status in (429,503):assert error.value.delay==180

@pytest.mark.parametrize('method,expected',[('GET',tinder.TinderProtocolError),('POST',tinder.TinderUncertain)])
async def test_corrupt_compression_is_controlled_and_never_retries_a_send(store,method,expected):
    calls=[]
    class Corrupt(httpx.AsyncByteStream):
        async def __aiter__(self):yield b'invalid-gzip-data'
    def handle(req):
        calls.append(req)
        return httpx.Response(200,headers={'Content-Encoding':'gzip'},stream=Corrupt())
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)) as api:
        with pytest.raises(expected):await api.request(method,'/profile' if method=='GET' else '/user/matches/match-a')
    assert len(calls)==1

async def test_compressed_response_limit_applies_to_decoded_size(store):
    body=gzip.compress(b'x'*(4*1024*1024+1))
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(lambda req:httpx.Response(
        200,headers={'Content-Encoding':'gzip'},content=body))) as api:
        with pytest.raises(tinder.TinderProtocolError,match='source_response_too_large'):await api.profile()

def test_api_connect_accepts_compressed_profile_without_internal_failure(store,monkeypatch):
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN',TOKEN)
    def handle(req):
        value={'data':{'_id':OWNER}} if req.url.path=='/profile' else {'data':{'matches':[]}}
        body=gzip.compress(json.dumps(value).encode())
        return httpx.Response(200,headers={'Content-Type':'application/json','Content-Encoding':'gzip'},content=body)
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(
        handle)))
    with TestClient(app,headers={'Authorization':'Bearer test-dashboard-token-at-least-32-chars'}) as client:
        result=client.post('/api/tinder/connect',json={'account_owned':True,'acknowledge_unofficial':True})
        assert result.status_code==200 and result.json()['connection_id']==CID
        assert not s.rows('SELECT * FROM actions') and not s.rows('SELECT * FROM grants')

def test_connect_rejects_profile_only_access_without_creating_enabled_account(store,monkeypatch):
    from fastapi.testclient import TestClient
    from app import app
    requests=[]
    def handle(req):
        requests.append(req)
        return httpx.Response(200,json={'data':{'_id':OWNER}}) if req.url.path=='/profile' else httpx.Response(401)
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN',TOKEN)
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)))
    with TestClient(app,headers={'Authorization':'Bearer test-dashboard-token-at-least-32-chars'}) as client:
        result=client.post('/api/tinder/connect',json={'account_owned':True,'acknowledge_unofficial':True})
        assert result.status_code==403 and 'inbox access (HTTP 401)' in result.json()['detail']
    assert [r.url.path for r in requests]==['/profile','/v2/matches']
    assert requests[1].url.params['count']=='60'
    assert not s.rows('SELECT * FROM connections') and not s.rows('SELECT * FROM actions')

async def test_inbox_401_preserves_precise_pause_reason_and_blocks_future_polls(store,monkeypatch):
    requests=[];denied=False
    def handle(req):
        requests.append(req)
        if req.url.path=='/profile':return httpx.Response(200,json={'data':{'_id':OWNER}})
        return httpx.Response(401) if denied else httpx.Response(200,json={'data':{'matches':[]}})
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN',TOKEN)
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)))
    await tinder.connect();denied=True;await tinder.poll()
    status=tinder.public_status()['connections'][0]
    assert not status['enabled'] and status['error']=='inbox_access_denied'
    before=len(requests);await tinder.poll();assert len(requests)==before

async def test_inbox_access_check_rejects_invalid_shape_before_connecting(store,monkeypatch):
    def handle(req):
        return httpx.Response(200,json={'data':{'_id':OWNER}} if req.url.path=='/profile' else {'data':{'matches':{}}})
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN',TOKEN)
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)))
    with pytest.raises(tinder.TinderProtocolError):await tinder.connect()
    assert not s.rows('SELECT * FROM connections')

def raw_message(mid='in-1',text='hey',sender=PERSON):
    return {'_id':mid,'message':text,'from':sender,'to':PERSON if sender==OWNER else OWNER,
            'match_id':'match-a','sent_date':datetime.now(timezone.utc).isoformat()}
class Source:
    def __init__(self):
        self.messages=[raw_message()];self.requests=[];self.posts=[];self.behavior='ok'
        self.profile_owner=OWNER;self.matches_visible=True;self.hide_sent=False;self.profile_status=200;self.new_id=0
    def handle(self,req):
        self.requests.append(req)
        assert req.url.host=='api.gotinder.com' and req.headers.get('X-Auth-Token')==TOKEN
        assert req.headers.get('platform') is None
        path=req.url.path
        if path=='/profile':return httpx.Response(self.profile_status,json={'data':{'_id':self.profile_owner}})
        if path=='/v2/matches':return httpx.Response(200,json={'data':{'matches':[
            {'_id':'match-a','person':{'_id':PERSON,'name':'Fictional Test Contact'}},
            {'_id':'match-b','person':{'_id':'person-b','name':'Empty fictional match'}}] if self.matches_visible else []}})
        if path=='/v2/matches/match-a/messages':
            rows=[m for m in self.messages if not self.hide_sent or m['from']!=OWNER]
            return httpx.Response(200,json={'data':{'messages':list(reversed(rows))}})
        if path=='/v2/matches/match-b/messages':return httpx.Response(200,json={'data':{'messages':[]}})
        if path=='/user/matches/match-a' and req.method=='POST':
            self.posts.append(json.loads(req.content));self.new_id+=1;text=self.posts[-1]['message'];mid=f'out-{self.new_id}'
            if self.behavior=='reject':return httpx.Response(400,json={'error':'invalid'})
            if self.behavior=='expire':return httpx.Response(401,json={'error':'expired'})
            if self.behavior=='rate_limit':return httpx.Response(429,headers={'Retry-After':'180'})
            if self.behavior=='server_error':return httpx.Response(503)
            if self.behavior=='old_receipt':return httpx.Response(200,json={'_id':self.messages[0]['_id']})
            sent=raw_message(mid,text,OWNER);self.messages.append(sent)
            if self.behavior=='timeout':raise httpx.ReadTimeout('simulated lost response',request=req)
            if self.behavior=='missing_receipt':return httpx.Response(200,json={'message':text})
            return httpx.Response(200,json=sent)
        return httpx.Response(404)
@pytest.fixture
def source(store,monkeypatch):
    fake=Source();monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN',TOKEN)
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(fake.handle)))
    return fake
async def setup_thread(source,grant=True):
    await tinder.connect();await tinder.sync_connection(CID)
    if grant:
        with s.connect() as db:db.execute('INSERT OR REPLACE INTO grants VALUES(?,?,?,?)',(TID,1,1,1))
    return service.thread_by_id(TID)
def model_stub(monkeypatch):
    monkeypatch.setattr(service,'generate',lambda *a:(Decision(action='reply',reply='hey :)',note='offline model stub',claims=[]),'LLM-reviewed:offline-test'))
async def ready(source,monkeypatch):
    t=await setup_thread(source);model_stub(monkeypatch);await tinder.sync_connection(CID)
    while (job:=rt.claim()):await service.process_job(job)
    return t
async def test_connect_auto_mode_discovery_empty_and_scope(source):
    t=await setup_thread(source,grant=False)
    assert rt.settings()['mode']=='supervised' and t['platform']=='tinder'
    assert s.messages(TID)[-1]['sender']=='them' and s.messages('tinder:owner-a:match-b')==[]
    assert not rt.auto_allowed(t) and not source.posts
    assert not [r for r in s.all_drafts() if r['thread_id']==TID]
async def test_automatic_reply_no_approval_and_no_duplicates(source,monkeypatch):
    await ready(source,monkeypatch)
    assert source.posts==[{'message':'hey :)'}]
    a=s.rows('SELECT * FROM actions WHERE thread_id=?',(TID,))[0]
    assert a['status']=='sent' and a['automatic']==1 and a['receipt']==TID+':out-1'
    await service.tick();await tinder.sync_connection(CID);await service.tick()
    assert len(source.posts)==1 and s.messages(TID)[-1]['sender']=='you'
@pytest.mark.parametrize('behavior',['timeout','server_error','missing_receipt','old_receipt'])
async def test_uncertain_post_never_retried_or_falsely_confirmed(source,monkeypatch,behavior):
    source.behavior=behavior
    if behavior=='old_receipt':
        old=raw_message('old-out','hey :)',OWNER);old['sent_date']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat();source.messages.insert(0,old)
    await ready(source,monkeypatch)
    assert len(source.posts)==1
    assert s.rows('SELECT status FROM actions WHERE thread_id=?',(TID,))[0]['status']=='uncertain'
    for _ in range(2):await service.reconcile();await service.tick()
    assert len(source.posts)==1
    assert s.rows('SELECT status FROM actions WHERE thread_id=?',(TID,))[0]['status']=='uncertain'
async def test_delayed_receipt_reconciles_exact_id(source,monkeypatch):
    source.hide_sent=True;await ready(source,monkeypatch)
    a=s.rows('SELECT * FROM actions WHERE thread_id=?',(TID,))[0];assert a['status']=='uncertain'
    assert s.rows('SELECT * FROM tinder_receipts WHERE action_id=?',(a['id'],))
    rt.recover();source.hide_sent=False;await service.reconcile()
    assert s.rows('SELECT status FROM actions WHERE id=?',(a['id'],))[0]['status']=='sent' and len(source.posts)==1
@pytest.mark.parametrize('behavior',['expire','rate_limit','reject'])
async def test_known_rejection_not_retried(source,monkeypatch,behavior):
    source.behavior=behavior;await ready(source,monkeypatch)
    assert s.rows('SELECT status FROM actions WHERE thread_id=?',(TID,))[0]['status']=='rejected'
    assert len(source.posts)==1
    if behavior=='expire':assert s.rows('SELECT enabled FROM connections WHERE id=?',(CID,))[0]['enabled']==0
    if behavior=='rate_limit':
        with pytest.raises(tinder.TinderRateLimited):tinder.connection(CID)
    await service.tick();assert len(source.posts)==1
async def test_final_refresh_blocks_arriving_message(source,monkeypatch):
    original=tinder.TinderAdapter.send
    async def incoming(self,thread,text,action_id,anchor):
        source.messages.append(raw_message('new-in','wait, change of plans'))
        return await original(self,thread,text,action_id,anchor)
    monkeypatch.setattr(tinder.TinderAdapter,'send',incoming)
    with pytest.raises(StaleAction):await ready(source,monkeypatch)
    assert not source.posts and s.rows('SELECT status FROM actions WHERE thread_id=?',(TID,))[0]['status']=='stale'
async def test_revoke_after_refresh_before_post(source,monkeypatch):
    original=tinder.TinderClient.messages;revoked=False
    async def revoke(self,*args):
        nonlocal revoked
        page=await original(self,*args)
        if s.rows("SELECT 1 FROM actions WHERE thread_id=? AND status='sending'",(TID,)):
            with s.connect() as db:db.execute('UPDATE grants SET enabled=0 WHERE thread_id=?',(TID,))
            revoked=True
        return page
    monkeypatch.setattr(tinder.TinderClient,'messages',revoke)
    with pytest.raises(StaleAction):await ready(source,monkeypatch)
    assert revoked and not source.posts
async def test_global_pause(source,monkeypatch):
    t=await setup_thread(source);model_stub(monkeypatch)
    cfg=rt.settings();cfg['paused']=True;rt.save_settings(cfg)
    await tinder.sync_connection(CID);await service.tick()
    assert not rt.auto_allowed(t) and not source.posts
async def test_unknown_sender_and_media_fail_closed(source):
    source.messages[0]['from']='unknown';await setup_thread(source)
    assert service.thread_by_id(TID)['source_visibility']=='not_observed' and not s.messages(TID)
    source.messages[0]['from']=PERSON;source.messages[0]['message']='';await tinder.sync_connection(CID)
    assert service.thread_by_id(TID)['source_visibility']=='not_observed'
async def test_token_change_blocks_access(source,monkeypatch):
    t=await setup_thread(source);monkeypatch.setenv('TINDER_AUTH_TOKEN','different-token')
    assert not rt.eligible(t)
    with pytest.raises(tinder.TinderAuthError):await adapter(t).snapshot(t)
    assert not source.posts
async def test_expired_profile_disables_connection(source):
    await setup_thread(source);source.profile_status=401;tinder.status_update(CID,delay=0);await tinder.poll()
    assert s.rows('SELECT enabled FROM connections WHERE id=?',(CID,))[0]['enabled']==0
    calls=len(source.requests);await tinder.poll();assert len(source.requests)==calls
async def test_missing_match_unknown_and_deleted_not_reimported(source):
    await setup_thread(source);source.matches_visible=False;await tinder.sync_connection(CID)
    assert service.thread_by_id(TID)['source_visibility']=='not_observed'
    rt.delete_thread(TID);source.matches_visible=True;await tinder.sync_connection(CID)
    assert not service.thread_by_id(TID) and not s.rows('SELECT * FROM tinder_threads WHERE thread_id=?',(TID,))
async def test_pagination_read_retries_and_caps(store):
    calls=[]
    def handle(req):
        calls.append(req)
        if len(calls)==1:return httpx.Response(503)
        cursor=req.url.params.get('page_token')
        return httpx.Response(200,json={'data':{'matches':[{'_id':'m2' if cursor else 'm1'}],**({} if cursor else {'next_page_token':'next'})}})
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)) as api:
        p=await api.matches();assert p.complete and [m['_id'] for m in p.items]==['m1','m2']
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle),max_pages=1) as api:
        assert not (await api.matches()).complete
async def test_pagination_cycles_and_redirect_fail_closed(store):
    def cyclic(req):return httpx.Response(200,json={'data':{'matches':[],'next_page_token':'same'}})
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(cyclic)) as api:
        with pytest.raises(tinder.TinderProtocolError):await api.matches()
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(lambda req:httpx.Response(302,headers={'Location':'https://evil.example'}))) as api:
        with pytest.raises(tinder.TinderRestriction):await api.profile()
async def test_owner_pin_and_secret_redaction(source,monkeypatch):
    monkeypatch.setenv('TINDER_OWNER_ID','someone-else')
    with pytest.raises(tinder.TinderAuthError):await tinder.connect()
    monkeypatch.delenv('TINDER_OWNER_ID');await tinder.connect()
    public=json.dumps(tinder.public_status());assert TOKEN not in public and 'credential_fingerprint' not in public
    assert TOKEN not in json.dumps(s.rows('SELECT * FROM activity'))
async def test_api_connect_autonomy_and_secret_redaction(source):
    from fastapi.testclient import TestClient
    from app import app
    with TestClient(app,headers={'Authorization':'Bearer test-dashboard-token-at-least-32-chars'}) as c:
        assert c.post('/api/tinder/connect',json={'account_owned':False,'acknowledge_unofficial':True}).status_code==422
        r=c.post('/api/tinder/connect',json={'account_owned':True,'acknowledge_unofficial':True})
        assert r.status_code==200 and r.json()['automatic_sending'] is True
        state=c.get('/api/state');assert TOKEN not in state.text
        assert state.json()['settings']['mode']=='supervised'
        assert c.post('/api/connections/'+CID+'/revoke').status_code==200
        assert not tinder.public_status()['connections'][0]['enabled']

async def test_partial_history_never_overwrites_or_sends(source,monkeypatch):
    await setup_thread(source)
    before=s.source_for_thread(TID)
    original=tinder.TinderClient.messages
    async def partial(self,*args):
        page=await original(self,*args)
        return tinder.Page(page.items,False)
    monkeypatch.setattr(tinder.TinderClient,'messages',partial)
    await tinder.sync_connection(CID)
    assert s.source_for_thread(TID)==before
    assert service.thread_by_id(TID)['source_visibility']=='not_observed' and not source.posts

async def test_account_identity_cannot_silently_change(source):
    t=await setup_thread(source);source.profile_owner='owner-b'
    with pytest.raises(tinder.TinderAuthError):await tinder.TinderAdapter().snapshot(t)
    assert s.rows('SELECT enabled FROM connections WHERE id=?',(CID,))[0]['enabled']==0
    assert not source.posts

async def test_missing_receipt_blocks_later_incoming_turn(source,monkeypatch):
    source.behavior='timeout';await ready(source,monkeypatch)
    source.messages.append(raw_message('later-in','are you there?'))
    await tinder.sync_connection(CID)
    # A later incoming turn may be drafted, but an unresolved earlier delivery forbids dispatch.
    await service.tick()
    assert len(source.posts)==1
    assert any(a['status']=='uncertain' for a in s.rows('SELECT * FROM actions WHERE thread_id=?',(TID,)))

async def test_read_rate_limit_defers_network_without_retry_storm(source):
    await setup_thread(source)
    original=source.handle
    def limited(req):
        if req.url.path=='/profile':
            source.requests.append(req);return httpx.Response(429,headers={'Retry-After':'180'})
        return original(req)
    monkeypatch=pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(limited)))
        tinder.status_update(CID,delay=0);await tinder.poll();count=len(source.requests)
        await tinder.poll();assert len(source.requests)==count
        assert tinder.public_status()['connections'][0]['error']=='rate_limited'
    finally:monkeypatch.undo()
