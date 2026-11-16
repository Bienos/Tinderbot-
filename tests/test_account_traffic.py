"""Traffic reduction and restriction-stop tests, not ban/detection-success tests."""
import json,time
from datetime import datetime,timezone,timedelta
from email.utils import format_datetime
import httpx,pytest
from agent import tinder,tinder_traffic as traffic,storage as s,runtime as rt,service
from agent.limits import check_send_budget,BudgetExceeded
from test_tinder import Source,OWNER,PERSON,CID,TID,TOKEN,raw_message,setup_thread,ready,source

async def test_local_request_budget_persists_across_client_instances(store,monkeypatch):
    monkeypatch.setenv('TINDER_REQUESTS_PER_MINUTE','2');calls=[]
    def handle(req):calls.append(req);return httpx.Response(200,json={'data':{'_id':OWNER}})
    for _ in range(2):
        async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)) as api:await api.profile()
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)) as api:
        with pytest.raises(tinder.TinderRateLimited) as e:await api.profile()
    assert e.value.reason=='local_request_budget' and len(calls)==2
    assert len(s.rows('SELECT * FROM tinder_requests'))==2

def test_retry_after_supports_long_delta_and_http_date_without_shortening():
    assert traffic.retry_after('7200')==7200
    date=format_datetime(datetime.now(timezone.utc)+timedelta(hours=2),usegmt=True)
    assert 7199<=traffic.retry_after(date)<=7201
    assert traffic.retry_after('invalid')==300
    with pytest.raises(OverflowError):traffic.retry_after('9999999999999999999999999')

async def test_cooldown_survives_reconnect_attempt(source,monkeypatch):
    await setup_thread(source)
    tinder.status_update(CID,error='rate_limited',delay=7200)
    before=len(source.requests)
    with pytest.raises(tinder.TinderRateLimited):await tinder.connect()
    assert len(source.requests)==before
    value=json.loads(s.rows('SELECT value FROM connections WHERE id=?',(CID,))[0]['value'])
    assert value['blocked_until']>time.time()+7100

@pytest.mark.parametrize('status',[403,423,451])
async def test_restrictions_disable_account_without_more_requests(source,status):
    await setup_thread(source)
    original=source.handle
    def restricted(req):
        if req.url.path=='/profile':source.requests.append(req);return httpx.Response(status)
        return original(req)
    # The test factory alone changes; no external request is made.
    patch=pytest.MonkeyPatch()
    try:
        patch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(restricted)))
        tinder.status_update(CID,delay=0);await tinder.poll();count=len(source.requests)
        assert not tinder.public_status()['connections'][0]['enabled']
        await tinder.poll();assert len(source.requests)==count
    finally:patch.undo()

async def test_verification_html_pauses_instead_of_attempting_challenge(source,monkeypatch):
    await setup_thread(source)
    calls=[]
    def challenge(req):calls.append(req);return httpx.Response(200,text='<html>Verify you are human: CAPTCHA</html>',headers={'Content-Type':'text/html'})
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(challenge)))
    tinder.status_update(CID,delay=0);await tinder.poll();await tinder.poll()
    assert len(calls)==1 and not tinder.public_status()['connections'][0]['enabled']

async def test_repeated_protocol_failure_opens_circuit(source,monkeypatch):
    await setup_thread(source);calls=[]
    def malformed(req):calls.append(req);return httpx.Response(200,json={'unexpected':True})
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(malformed)))
    for _ in range(3):
        tinder.status_update(CID,delay=0);await tinder.poll()
    status=tinder.public_status()['connections'][0]
    assert not status['enabled'] and status['error']=='circuit_open_requires_review'
    await tinder.poll();assert len(calls)==3

async def test_unchanged_ungranted_threads_use_cache_and_backoff(source):
    await setup_thread(source,grant=False)
    before=len(source.requests);await tinder.sync_connection(CID)
    assert len(source.requests)-before==3 # profile + new-matches list + conversations list, no repeated histories
    state=json.loads(s.rows('SELECT value FROM connections WHERE id=?',(CID,))[0]['value'])
    assert state['idle_rounds']==1 and state['next_poll']>time.time()+tinder.poll_interval()

async def test_activity_metadata_change_refreshes_inactive_thread(source,monkeypatch):
    await setup_thread(source,grant=False)
    source.messages.append(raw_message('new-in','new content'))
    original=source.handle
    def changed(req):
        r=original(req)
        if req.url.path=='/v2/matches':
            data=r.json();data['data']['matches'][0]['last_activity_date']='2026-11-15T15:00:00Z'
            return httpx.Response(200,json=data)
        return r
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(changed)))
    await tinder.sync_connection(CID)
    assert s.source_for_thread(TID)[-1]['body']=='new content'

async def test_global_pause_stops_background_network(source):
    await setup_thread(source);cfg=rt.settings();cfg['paused']=True;rt.save_settings(cfg)
    before=len(source.requests);await tinder.poll()
    assert len(source.requests)==before

async def test_paused_thread_history_not_polled(source):
    await setup_thread(source);s.set_thread_flags(TID,paused=True)
    before=len(source.requests);await tinder.sync_connection(CID)
    assert len(source.requests)-before==3

async def test_uncertain_receipt_reconciliation_is_throttled(source,monkeypatch):
    source.hide_sent=True;await ready(source,monkeypatch)
    before=len(source.requests);await service.reconcile();first=len(source.requests)
    assert first>before
    await service.reconcile();assert len(source.requests)==first
    source.hide_sent=False
    with s.connect() as db:db.execute('UPDATE tinder_receipts SET next_check=0')
    await service.reconcile()
    assert s.rows('SELECT status FROM actions WHERE thread_id=?',(TID,))[0]['status']=='sent'
    assert len(source.posts)==1

async def test_tinder_specific_send_budget(source,monkeypatch):
    await setup_thread(source);monkeypatch.setenv('TINDER_SENDS_PER_DAY','1')
    with s.connect() as db:
        db.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)',('prior',-1,TID,'old','sent','receipt',time.time()-7200,1))
    with s.connect() as db:
        with pytest.raises(BudgetExceeded):check_send_budget(db,TID)

async def test_service_retry_after_header_is_respected_without_read_retries(store):
    calls=[]
    def unavailable(req):calls.append(req);return httpx.Response(503,headers={'Retry-After':'7200'})
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(unavailable)) as api:
        with pytest.raises(tinder.TinderRateLimited) as e:await api.profile()
    assert e.value.delay==7200 and e.value.reason=='server_retry_after' and len(calls)==1

async def test_repeated_daily_rate_limits_require_manual_review(source):
    await setup_thread(source)
    for _ in range(3):tinder.status_update(CID,error='rate_limited',delay=60)
    status=tinder.public_status()['connections'][0]
    assert not status['enabled'] and status['error']=='repeated_rate_limits_requires_review'
    assert status['blocked_until']>time.time()+1100

async def test_post_503_retry_after_remains_uncertain_and_is_not_retried(store):
    calls=[]
    def unavailable(req):calls.append(req);return httpx.Response(503,headers={'Retry-After':'7200'})
    async with tinder.TinderClient(TOKEN,transport=httpx.MockTransport(unavailable)) as api:
        with pytest.raises(tinder.TinderUncertain):await api.send_once('match-a','test')
    assert len(calls)==1

async def test_circuit_pause_is_recorded_once_for_owner_review(source):
    await setup_thread(source)
    tinder.status_update(CID,error='restriction_requires_manual_review',disable=True)
    tinder.status_update(CID,error='restriction_requires_manual_review',disable=True)
    events=s.rows("SELECT * FROM activity WHERE event='tinder_connection_paused'")
    assert len(events)==1 and events[0]['detail'] in ('restriction_requires_manual_review','circuit_open_requires_review')

async def test_existing_cooldown_checks_do_not_count_as_new_server_throttles(source):
    t=await setup_thread(source)
    tinder.status_update(CID,error='rate_limited',delay=7200)
    before=len(source.requests)
    for _ in range(4):
        with pytest.raises(tinder.TinderRateLimited):await tinder.TinderAdapter().snapshot(t)
    value=json.loads(s.rows('SELECT value FROM connections WHERE id=?',(CID,))[0]['value'])
    assert len(value['rate_limit_events'])==1
    assert tinder.public_status()['connections'][0]['enabled'] and len(source.requests)==before


def test_import_budget_only_until_first_full_import(store,monkeypatch):
    import json
    from agent import storage as s, tinder_traffic as traffic
    from agent.tinder import clear_local_budget_block
    monkeypatch.delenv('TINDER_REQUESTS_PER_MINUTE',raising=False);monkeypatch.delenv('TINDER_REQUESTS_PER_HOUR',raising=False)
    with s.connect() as db:db.execute("INSERT INTO connections VALUES('tinder:o',1,1,'o',?)",(json.dumps({'error':None}),))
    assert traffic.import_phase() and traffic.caps()==[(60,120),(3600,1000)]
    with s.connect() as db:db.execute("UPDATE connections SET value=? WHERE id='tinder:o'",(json.dumps({'initial_import_done':True}),))
    assert not traffic.import_phase() and traffic.caps()==[(60,30),(3600,300)]
    clear_local_budget_block()
    assert traffic.import_phase()


async def test_owner_bio_check_is_not_blocked_by_our_own_local_budget(source):
    """The 'Sprawdź ponownie' button must work while the sync has used up the local budget; Tinder's own cooldown still wins."""
    await tinder.connect()
    tinder.status_update(CID,error='local_request_budget',delay=1800)
    source.owner_bio='Używam AI czasami'
    assert (await tinder.check_bio(CID))['found'] is True
    tinder.status_update(CID,error='rate_limited',delay=7200)
    before=len(source.requests)
    with pytest.raises(tinder.TinderRateLimited) as e:await tinder.check_bio(CID)
    assert not tinder.is_local_limit(e.value) and len(source.requests)==before

async def test_blocked_sync_reports_that_the_limit_is_local(source):
    await tinder.connect()
    tinder.status_update(CID,error='local_request_budget',delay=1800)
    with pytest.raises(tinder.TinderRateLimited) as e:await tinder.TinderAdapter().snapshot(setup_thread_stub())
    assert tinder.is_local_limit(e.value)

def setup_thread_stub():
    return {'connection_id':CID,'id':TID,'chat_id':'x'}

async def test_owner_checks_have_their_own_small_cap(store,monkeypatch):
    monkeypatch.setattr(traffic,'_OWNER_CHECKS',[])
    for _ in range(6):traffic.claim_request(owner=True)
    with pytest.raises(traffic.TrafficBudget):traffic.claim_request(owner=True)


def _profile_with_interests(monkeypatch,source,names):
    real=source.handle
    def handle(req):
        if req.url.path=='/v2/profile':
            source.requests.append(req)
            return httpx.Response(200,json={'data':{'user':{'_id':OWNER,'bio':'x','user_interests':{'selected_interests':[{'id':str(i),'name':n} for i,n in enumerate(names)]}}}})
        return real(req)
    monkeypatch.setattr(tinder,'client',lambda:tinder.TinderClient(TOKEN,transport=httpx.MockTransport(handle)))

async def test_profile_sync_fills_empty_interests_even_when_inbox_budget_is_used_up(source,monkeypatch):
    await tinder.connect()
    tinder.status_update(CID,error='local_request_budget',delay=1800)
    _profile_with_interests(monkeypatch,source,['Bieganie','Planszówki'])
    r=await tinder.sync_profile(CID)
    assert r=={'interests':['Bieganie','Planszówki'],'filled':True}
    assert rt.settings()['profile']['zainteresowania']=='Bieganie, Planszówki'

async def test_profile_sync_never_overwrites_what_the_owner_wrote(source,monkeypatch):
    await tinder.connect()
    cfg=rt.settings();cfg['profile']={'zainteresowania':'góry, kawa'};rt.save_settings(cfg)
    _profile_with_interests(monkeypatch,source,['Bieganie'])
    r=await tinder.sync_profile(CID)
    assert r['filled'] is False and rt.settings()['profile']['zainteresowania']=='góry, kawa'

async def test_profile_sync_respects_a_cooldown_from_tinder(source,monkeypatch):
    await tinder.connect()
    tinder.status_update(CID,error='rate_limited',delay=7200)
    _profile_with_interests(monkeypatch,source,['Bieganie']);before=len(source.requests)
    with pytest.raises(tinder.TinderRateLimited):await tinder.sync_profile(CID)
    assert len(source.requests)==before


def test_a_conversation_that_could_not_be_read_is_not_retried_every_poll(store, monkeypatch):
    """Unreadable chats (unsupported media, huge histories) used to be re-read on every poll and ate the whole hourly budget."""
    import time
    from agent import tinder_traffic as traffic
    thread = {'id': 't', 'user_paused': 0, 'user_archived': 0, 'source_visibility': 'not_observed'}
    now = time.time()
    failed = {'last_read': now - 10, 'read_failed': True, 'failed_at': now - 60}
    assert traffic.should_read(thread, failed, 'k', now) is False                  # failed a minute ago: leave it alone
    assert traffic.should_read(thread, {**failed, 'failed_at': now - 3700}, 'k', now) is True   # an hour later: try again
    monkeypatch.setenv('TINDER_FAILED_THREAD_RETRY', '120')
    assert traffic.should_read(thread, {**failed, 'failed_at': now - 130}, 'k', now) is True
    # a healthy but never-read conversation is still read at once
    assert traffic.should_read({**thread, 'source_visibility': 'available'}, None, 'k', now) is True
