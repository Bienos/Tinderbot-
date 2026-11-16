"""Nightly rollout of new bot versions: one bot at a time, health-checked, rolled back and stopped on the first failure."""
import json
from datetime import datetime,timezone
import httpx,pytest
from fastapi.testclient import TestClient

REG={'email':'a@example.com','password':'bardzo-tajne-haslo','name':'A','adult':True,'terms':True}
ADMIN={'Authorization':'Bearer '+'a'*32}
SHA1,SHA2='1'*40,'2'*40

@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setenv('CONTROL_DB_PATH',str(tmp_path/'c.db'));monkeypatch.setenv('ADMIN_TOKEN','a'*32)
    monkeypatch.setenv('FLY_IMAGE','registry.fly.io/imgapp:latest');monkeypatch.setenv('FLY_API_TOKEN','FlyV1 x')
    monkeypatch.setenv('RENDER_API_KEY','rnd_x');monkeypatch.setenv('RENDER_OWNER_ID','tea-x');monkeypatch.setenv('OWNER_SERVICE_ID','srv-owner')
    for k in ('STRIPE_PAYMENT_LINK','STRIPE_WEBHOOK_SECRET','STRIPE_SECRET_KEY','STRIPE_PRICE_ID'):monkeypatch.delenv(k,raising=False)   # no billing: everyone has access
    import control.app as capp
    capp._HITS.clear();return capp

class World:
    """GitHub says which build is newest; fake Fly and Render record what the rollout does to them."""
    def __init__(self,monkeypatch):
        from control import rollout,fly,provision
        self.sha=SHA1;self.log=[];self.images={};self.render_status={};self.health_fails=set();self.fly_rollback_fails=False
        gh=lambda request:httpx.Response(200,json={'workflow_runs':[{'head_sha':self.sha}]})
        monkeypatch.setattr(rollout,'TRANSPORT',httpx.MockTransport(gh))
        monkeypatch.setattr(fly,'current_image',lambda app:self.images.get(app,'registry.fly.io/imgapp@sha256:old-'+app))
        def update(app,image):
            self.log.append(('fly',app,image))
            if self.fly_rollback_fails and '@sha256' in image:raise RuntimeError('fly api down')
            if self.images.get(app)==image:return 'unchanged'
            self.images[app]=image;return 'updated'
        monkeypatch.setattr(fly,'update_image',update)
        monkeypatch.setattr(fly,'deploy_status',lambda app:'live')
        monkeypatch.setattr(provision,'trigger_deploy',lambda sid:self.log.append(('render',sid)))
        monkeypatch.setattr(provision,'deploy_status',lambda sid:self.render_status.get(sid,'live'))
        monkeypatch.setattr(rollout,'WAIT_FLY',0.05)
    def health(self,acc,base_for):
        if acc and acc['render_service_id'] in self.health_fails:raise RuntimeError('summary did not answer')

@pytest.fixture
def world(monkeypatch):return World(monkeypatch)

def bot(c,n,service_id,**extra):
    email=f'u{n}@example.com';TestClient(c.app).post('/api/register',json={**REG,'email':email})
    fields={'render_service_id':service_id,'status':'active','instance_url':f'https://b{n}.example','sso_secret':'s'*40,'comped':0,**extra}
    for k,v in fields.items():c.q(f'UPDATE accounts SET {k}=? WHERE email=?',(v,email))

def go(c,world,**kw):
    from control import rollout
    alerts=[]
    out=rollout.run(c.q,has_access=c.has_access,base_for=c.panel_url,owner_service_id='srv-owner',alert=lambda s,t:alerts.append((s,t)),
                    sleep=lambda s:None,health=world.health,**kw)
    return out,alerts

def results(out):return [(i['service_id'],i['result']) for i in out['items']]

def test_latest_build_comes_from_the_last_successful_image_build(c,world):
    from control import rollout
    assert rollout.latest_build()=={'sha':SHA1,'tag':'git-'+'1'*12,'image':'registry.fly.io/imgapp:git-'+'1'*12}

def test_github_being_unreachable_changes_nothing(c,world,monkeypatch):
    from control import rollout
    monkeypatch.setattr(rollout,'TRANSPORT',httpx.MockTransport(lambda r:httpx.Response(503)))
    bot(c,1,'fly:winq-b-aaaa1111');out,alerts=go(c,world)
    assert out['result']=='no build found' and world.log==[] and alerts==[]

def test_order_is_fly_then_render_customers_then_the_owners_own_bot(c,world):
    bot(c,1,'srv-cust1');bot(c,2,'fly:winq-b-aaaa1111');bot(c,3,'fly:winq-b-bbbb2222')
    out,alerts=go(c,world)
    assert results(out)==[('fly:winq-b-aaaa1111','updated'),('fly:winq-b-bbbb2222','updated'),('srv-cust1','updated'),('srv-owner','updated')]
    assert world.log==[('fly','winq-b-aaaa1111','registry.fly.io/imgapp:git-'+'1'*12),('fly','winq-b-bbbb2222','registry.fly.io/imgapp:git-'+'1'*12),('render','srv-cust1'),('render','srv-owner')]
    assert out['result']=='done' and alerts==[]

def test_bots_already_on_the_newest_version_are_left_alone_until_a_new_one_appears(c,world):
    bot(c,1,'fly:winq-b-aaaa1111');go(c,world);world.log.clear()
    out,_=go(c,world);assert results(out)==[('fly:winq-b-aaaa1111','up to date'),('srv-owner','up to date')] and world.log==[]
    world.sha=SHA2;out,_=go(c,world)
    assert [r for _,r in results(out)]==['updated','updated'] and ('fly','winq-b-aaaa1111','registry.fly.io/imgapp:git-'+'2'*12) in world.log
    assert {r['target'] for r in c.q('SELECT target FROM rollout_state',fetch=True)}=={SHA2}

def test_the_first_bot_that_does_not_come_back_healthy_is_rolled_back_and_stops_the_run(c,world):
    bot(c,1,'fly:winq-b-aaaa1111');bot(c,2,'fly:winq-b-bbbb2222');bot(c,3,'srv-cust1')
    world.health_fails={'fly:winq-b-aaaa1111'}
    out,alerts=go(c,world)
    assert out['result']=='aborted'
    assert results(out)[0][1].startswith('failed') and 'rolled back' in results(out)[0][1]
    assert all(r=='skipped: run stopped after a failure' for _,r in results(out)[1:])                       # nobody else is touched
    assert world.log==[('fly','winq-b-aaaa1111','registry.fly.io/imgapp:git-'+'1'*12),('fly','winq-b-aaaa1111','registry.fly.io/imgapp@sha256:old-winq-b-aaaa1111')]   # back to the exact previous build
    row=c.q("SELECT status,error FROM rollout_state WHERE service_id='fly:winq-b-aaaa1111'",fetch=True)[0];assert row['status']=='failed' and 'rolled back' in row['error']
    assert len(alerts)==1 and 'winq-b-aaaa1111' in alerts[0][0] and 'git-'+'1'*12 in alerts[0][1] and 'Pozostałe boty nie zostały ruszone' in alerts[0][1]

def test_a_failed_rollback_is_reported_loudly(c,world):
    bot(c,1,'fly:winq-b-aaaa1111');world.health_fails={'fly:winq-b-aaaa1111'};world.fly_rollback_fails=True
    out,alerts=go(c,world);assert 'ROLLBACK FAILED' in results(out)[0][1] and alerts

def test_a_failed_bot_is_tried_again_at_the_next_run(c,world):
    bot(c,1,'fly:winq-b-aaaa1111');world.health_fails={'fly:winq-b-aaaa1111'};go(c,world)
    world.health_fails=set();out,alerts=go(c,world)
    assert results(out)[0]==('fly:winq-b-aaaa1111','updated') and alerts==[]

def test_a_render_build_that_fails_keeps_the_old_version_and_alerts(c,world):
    bot(c,1,'srv-cust1');world.render_status={'srv-cust1':'build_failed'}
    out,alerts=go(c,world)
    assert results(out)==[('srv-cust1','failed: deploy build_failed (the previous version keeps serving)'),('srv-owner','skipped: run stopped after a failure')]
    assert len(alerts)==1

def test_customers_without_a_running_subscription_are_skipped(c,world,monkeypatch):
    monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/x');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_x')   # billing on
    bot(c,1,'fly:winq-b-aaaa1111',plan_status='canceled');bot(c,2,'fly:winq-b-bbbb2222',plan_status='active');bot(c,3,'fly:winq-b-cccc3333',plan_status='none',comped=1)
    out,_=go(c,world)
    assert results(out)==[('fly:winq-b-aaaa1111','skipped: no running subscription'),('fly:winq-b-bbbb2222','updated'),('fly:winq-b-cccc3333','updated'),('srv-owner','updated')]

def test_dry_run_touches_nothing_and_force_rolls_bots_that_are_current(c,world):
    bot(c,1,'fly:winq-b-aaaa1111')
    out,_=go(c,world,dry_run=True);assert [r for _,r in results(out)]==['would update','would update'] and world.log==[] and c.q('SELECT 1 FROM rollout_state',fetch=True)==[]
    go(c,world);world.log.clear()
    out,_=go(c,world,force=True);assert [r for _,r in results(out)]==['unchanged','updated']                      # Fly says the bot already runs this image; Render redeploys

def test_without_hosting_credentials_nothing_is_attempted(c,world,monkeypatch):
    monkeypatch.delenv('FLY_API_TOKEN');monkeypatch.delenv('RENDER_API_KEY')
    bot(c,1,'fly:winq-b-aaaa1111');out,_=go(c,world);assert all(r=='skipped: hosting API is not configured' for _,r in results(out)) and world.log==[]

def test_the_nightly_run_starts_once_in_the_early_hours(c):
    from control import rollout
    at=lambda h,d=16:datetime(2026,11,d,h,0,tzinfo=timezone.utc).timestamp()                                       # UTC+1 in November: 02:00 UTC is 03:00 in Warsaw
    assert not rollout.due(c.q,at(1)) and rollout.due(c.q,at(2)) and rollout.due(c.q,at(3)) and not rollout.due(c.q,at(4))   # 03:00-05:00 only
    rollout.claim_today(c.q,at(2));assert not rollout.due(c.q,at(3)) and rollout.due(c.q,at(2,17))                # not again tonight, again tomorrow night

def test_a_freshly_created_bot_is_not_restarted_for_nothing(c,world):
    from control import rollout
    bot(c,1,'fly:winq-b-aaaa1111');rollout.mark_current(c.q,'fly:winq-b-aaaa1111')
    out,_=go(c,world);assert results(out)[0]==('fly:winq-b-aaaa1111','up to date')

def test_a_removed_bot_leaves_the_rollout_state(c,world,monkeypatch):
    from control import provision
    bot(c,1,'fly:winq-b-aaaa1111');go(c,world)
    monkeypatch.setattr(provision,'delete_instance',lambda sid:None)
    c.q('INSERT INTO instance_removals(service_id,created) VALUES(?,?)',('fly:winq-b-aaaa1111',1.0));c.remove_pending_instances()
    assert c.q("SELECT 1 FROM rollout_state WHERE service_id='fly:winq-b-aaaa1111'",fetch=True)==[]

def test_admin_endpoints(c,world):
    cl=TestClient(c.app)
    assert cl.get('/admin/rollout').status_code==401 and cl.post('/admin/rollout/run',json={}).status_code==401
    bot(c,1,'fly:winq-b-aaaa1111');go(c,world);world.sha=SHA2
    d=cl.get('/admin/rollout',headers=ADMIN).json();assert d['target']['sha']==SHA2 and set(d['behind'])=={'fly:winq-b-aaaa1111','srv-owner'} and d['running'] is False
    r=cl.post('/admin/rollout/run',headers=ADMIN,json={'dry_run':True}).json();assert [i['result'] for i in r['items']]==['would update','would update']

def test_the_machine_image_is_pinned_by_digest_for_rollbacks(monkeypatch):
    from control import fly
    ms=[{'id':'m1','config':{'image':'registry.fly.io/imgapp:latest'},'image_ref':{'registry':'registry.fly.io','repository':'imgapp','tag':'latest','digest':'sha256:abc'}}]
    monkeypatch.setenv('FLY_API_TOKEN','FlyV1 x');monkeypatch.setattr(fly,'TRANSPORT',httpx.MockTransport(lambda r:httpx.Response(200,json=ms)))
    assert fly.current_image('winq-b-aaaa1111')=='registry.fly.io/imgapp@sha256:abc'
    ms[0]['image_ref']={};assert fly.current_image('winq-b-aaaa1111')=='registry.fly.io/imgapp:latest'

def test_a_run_can_be_limited_to_one_provider(c,world):
    bot(c,1,'fly:winq-b-aaaa1111');bot(c,2,'srv-cust1')
    out,_=go(c,world,only='fly');assert results(out)==[('fly:winq-b-aaaa1111','updated')] and [e[0] for e in world.log]==['fly']   # Render bots are not even listed
    out,_=go(c,world,only='render');assert results(out)==[('srv-cust1','updated'),('srv-owner','updated')]
