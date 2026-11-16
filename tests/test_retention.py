"""Cancelling: survey, then one offer to stay (+5 conversations, -30% on the next payment). Promised only when it can be delivered."""
import json
import httpx,pytest
from fastapi.testclient import TestClient

REG={'email':'ola@example.com','password':'bardzo-tajne-haslo','name':'Ola','adult':True,'terms':True}
ADMIN={'Authorization':'Bearer '+'a'*32}
ANSWERS={'satisfaction':3,'reason':'price','note':'  za drogo jak na mnie  '}

@pytest.fixture
def c(tmp_path,monkeypatch):
    monkeypatch.setenv('CONTROL_DB_PATH',str(tmp_path/'c.db'));monkeypatch.setenv('ADMIN_TOKEN','a'*32)
    monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/x');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_x')
    monkeypatch.setenv('STRIPE_PORTAL_URL','https://billing.stripe.com/p/login/x')
    monkeypatch.setenv('FLY_API_TOKEN','FlyV1 fm2_x')
    import control.app as capp
    capp._HITS.clear();return capp

class FlyBot:
    """A fake Fly API for one bot: remembers the environment the control service sets on it."""
    def __init__(self):self.env={'PLAN':'flirt'};self.updates=[]
    def __call__(self,request):
        if request.method=='GET':return httpx.Response(200,json=[{'id':'m1','version':'v1','config':{'env':dict(self.env)}}])
        body=json.loads(request.content);self.env=body['config']['env'];self.updates.append(dict(self.env));return httpx.Response(200,json={})

@pytest.fixture
def bot(monkeypatch):
    from control import fly
    b=FlyBot();monkeypatch.setattr(fly,'TRANSPORT',httpx.MockTransport(b));return b

def customer(c,plan='flirt',period='1',email='ola@example.com',**extra):
    client=TestClient(c.app);client.post('/api/register',json={**REG,'email':email})
    fields={'plan':plan,'plan_period':period,'plan_status':'active','stripe_customer':'cus_1','render_service_id':'fly:winq-b-abcd1234','status':'active','comped':0,**extra}
    for k,v in fields.items():c.q(f'UPDATE accounts SET {k}=? WHERE email=?',(v,email))
    return client

def test_survey_is_validated_and_stored(c):
    cl=customer(c)
    assert cl.post('/api/cancel/feedback',json={**ANSWERS,'satisfaction':6}).status_code==422
    assert cl.post('/api/cancel/feedback',json={**ANSWERS,'satisfaction':True}).status_code==422
    assert cl.post('/api/cancel/feedback',json={**ANSWERS,'reason':'because'}).status_code==422
    assert TestClient(c.app).post('/api/cancel/feedback',json=ANSWERS).status_code==401
    assert cl.post('/api/cancel/feedback',json=ANSWERS).status_code==200
    cl.post('/api/cancel/feedback',json={**ANSWERS,'satisfaction':4})                       # answering again replaces the pending one
    rows=c.q('SELECT * FROM cancel_feedback',fetch=True);assert len(rows)==1 and rows[0]['satisfaction']==4 and rows[0]['outcome']=='pending'
    assert c.q('SELECT note FROM cancel_feedback',fetch=True)[0]['note']=='za drogo jak na mnie'
    me=cl.get('/api/me').json();assert {r['key'] for r in me['cancel_reasons']}>={'price','few_conversations','other'}

def test_without_a_stripe_key_the_offer_leaves_the_discount_out(c):
    cl=customer(c)
    assert cl.post('/api/cancel/feedback',json=ANSWERS).json()['offer']=={'bonus':5,'discount':0,'from':10,'to':15}

def test_with_a_stripe_key_a_monthly_customer_is_offered_both(c,monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_x')
    assert customer(c).post('/api/cancel/feedback',json=ANSWERS).json()['offer']['discount']==30

def test_longer_plans_are_not_offered_a_discount_they_would_pay_a_year_for(c,monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_x')
    assert customer(c,period='12').post('/api/cancel/feedback',json=ANSWERS).json()['offer']=={'bonus':5,'discount':0,'from':10,'to':15}

@pytest.mark.parametrize('extra',[{'comped':1},{'plan_status':'canceled'},{'render_service_id':None},{'stripe_customer':None},{'plan':None}])
def test_no_offer_without_a_paying_customer_with_a_running_bot(c,extra):
    assert customer(c,**extra).post('/api/cancel/feedback',json=ANSWERS).json()['offer'] is None

def test_accepting_gives_the_conversations_the_discount_and_a_mail_once(c,bot,monkeypatch):
    from control import mailer
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_x');mailer.SENT.clear()
    discounted=[];monkeypatch.setattr(c.retention,'apply_stay_discount',lambda cust:discounted.append(cust))
    cl=customer(c);cl.post('/api/cancel/feedback',json=ANSWERS)
    r=cl.post('/api/cancel/offer',json={'accept':True});assert r.status_code==200 and r.json()['accepted'] and r.json()['to']==15
    assert discounted==['cus_1'] and bot.env['PLAN_CONVERSATIONS']=='15' and bot.env['PLAN']=='flirt'      # 10 of the plan + 5
    row=c.q('SELECT retention_used_at,retention_plan,retention_applied FROM accounts',fetch=True)[0]
    assert row['retention_used_at'] and row['retention_plan']=='flirt' and row['retention_applied']==1
    assert c.q('SELECT outcome FROM cancel_feedback',fetch=True)[0]['outcome']=='accepted'
    assert [m['subject'] for m in mailer.SENT if 'zostajesz' in m['subject'].lower()]==['Zostajesz z Winq, dziękujemy']
    assert cl.post('/api/cancel/offer',json={'accept':True}).status_code==409                              # once per account
    assert cl.post('/api/cancel/feedback',json=ANSWERS).json()['offer'] is None and len(discounted)==1

def test_a_failing_discount_grants_nothing(c,bot,monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_x')
    def boom(cust):raise RuntimeError('stripe is down')
    monkeypatch.setattr(c.retention,'apply_stay_discount',boom)
    cl=customer(c);cl.post('/api/cancel/feedback',json=ANSWERS)
    assert cl.post('/api/cancel/offer',json={'accept':True}).status_code==502
    assert bot.updates==[] and c.q('SELECT retention_used_at FROM accounts',fetch=True)[0]['retention_used_at'] is None
    monkeypatch.setattr(c.retention,'apply_stay_discount',lambda cust:None)                               # Stripe is back: the offer is still there
    assert cl.post('/api/cancel/offer',json={'accept':True}).status_code==200 and bot.env['PLAN_CONVERSATIONS']=='15'

def test_declining_goes_to_stripe_and_remembers_the_answer(c):
    cl=customer(c);cl.post('/api/cancel/feedback',json=ANSWERS)
    r=cl.post('/api/cancel/offer',json={'accept':False});assert r.status_code==200 and r.json()['url'].startswith('https://billing.stripe.com/p/login/x?')
    assert c.q('SELECT outcome FROM cancel_feedback',fetch=True)[0]['outcome']=='declined'
    assert cl.post('/api/cancel/offer',json={}).json()['url'].startswith('https://billing.stripe.com')    # anything but an explicit accept is a decline

def test_a_bot_that_cannot_be_updated_now_is_retried_later(c,monkeypatch):
    from control import fly
    cl=customer(c);cl.post('/api/cancel/feedback',json=ANSWERS)
    down=httpx.MockTransport(lambda r:httpx.Response(500));monkeypatch.setattr(fly,'TRANSPORT',down)
    assert cl.post('/api/cancel/offer',json={'accept':True}).status_code==200                               # the customer still gets the offer
    assert c.q('SELECT retention_applied FROM accounts',fetch=True)[0]['retention_applied']==0
    b=FlyBot();monkeypatch.setattr(fly,'TRANSPORT',httpx.MockTransport(b))
    c.reapply_retention_bonuses();assert b.env['PLAN_CONVERSATIONS']=='15' and c.q('SELECT retention_applied FROM accounts',fetch=True)[0]['retention_applied']==1

def test_the_bonus_belongs_to_the_plan_it_was_taken_on(c,bot):
    cl=customer(c);cl.post('/api/cancel/feedback',json=ANSWERS);cl.post('/api/cancel/offer',json={'accept':True})
    c.q("UPDATE accounts SET plan='casanova'");c._apply_plan('fly:winq-b-abcd1234','casanova')             # upgraded in Stripe's portal
    assert bot.env['PLAN']=='casanova' and bot.env['PLAN_CONVERSATIONS']==''                              # back to the plan's own 30
    c.q("UPDATE accounts SET plan='flirt'");c._apply_plan('fly:winq-b-abcd1234','flirt')                    # and back: the bonus returns
    assert bot.env['PLAN_CONVERSATIONS']=='15'

def test_plan_changes_of_customers_without_the_offer_are_untouched(c,bot):
    customer(c);c._apply_plan('fly:winq-b-abcd1234','casanova')
    assert bot.env=={'PLAN':'casanova'}                                                                     # no PLAN_CONVERSATIONS appears out of nowhere

def test_deleting_the_account_keeps_the_answers_without_the_person(c,bot):
    cl=customer(c);cl.post('/api/cancel/feedback',json=ANSWERS);cl.post('/api/cancel/offer',json={'accept':False})
    assert cl.post('/api/account/delete',json={'password':REG['password']}).status_code==200
    row=c.q('SELECT account_id,note,reason,satisfaction FROM cancel_feedback',fetch=True)[0]
    assert row['account_id'] is None and row['note'] is None and row['reason']=='price' and row['satisfaction']==3

def test_admin_sees_why_customers_leave(c):
    assert TestClient(c.app).get('/admin/cancel-feedback').status_code==401
    a=customer(c);a.post('/api/cancel/feedback',json=ANSWERS);a.post('/api/cancel/offer',json={'accept':False})
    b=customer(c,email='jan@example.com');b.post('/api/cancel/feedback',json={'satisfaction':5,'reason':'met_someone'});b.post('/api/cancel/offer',json={'accept':False})
    d=TestClient(c.app).get('/admin/cancel-feedback',headers=ADMIN).json()
    assert d['count']==2 and d['declined']==2 and d['average_satisfaction']==4.0 and d['by_reason']=={'price':1,'met_someone':1}
    assert {i['email'] for i in d['items']}=={'ola@example.com','jan@example.com'}

def test_the_status_page_offers_the_cancel_step_only_to_paying_customers():
    js=open('control/static/account.js',encoding='utf-8').read()
    assert 'me.can_manage_billing&&me.has_access&&me.cancel_reasons' in js and 'function cancelFlow' in js

def test_the_stripe_call_creates_the_coupon_once_and_keeps_existing_discounts(monkeypatch):
    stripe=pytest.importorskip('stripe')
    from control import retention
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_x')
    calls=[];made={'coupon':False}
    def retrieve(cid,**kw):
        if not made['coupon']:raise stripe.InvalidRequestError('No such coupon','id')
    def create(**kw):made['coupon']=True;calls.append(('coupon',kw['id'],kw['percent_off'],kw['duration']))
    class Sub(dict):pass
    subs=type('L',(),{'data':[Sub(id='sub_old',status='canceled',discounts=[]),Sub(id='sub_live',status='active',discounts=[{'coupon':{'id':'loyal-10'}}])]})
    monkeypatch.setattr(stripe.Coupon,'retrieve',staticmethod(retrieve));monkeypatch.setattr(stripe.Coupon,'create',staticmethod(create))
    monkeypatch.setattr(stripe.Subscription,'list',staticmethod(lambda **kw:subs))
    monkeypatch.setattr(stripe.Subscription,'modify',staticmethod(lambda sid,**kw:calls.append(('modify',sid,kw['discounts']))))
    retention.apply_stay_discount('cus_1')
    assert calls==[('coupon','winq-stay-30',30,'once'),('modify','sub_live',[{'coupon':'loyal-10'},{'coupon':'winq-stay-30'}])]   # the loyalty discount stays
    subs.data[1]['discounts']=[{'coupon':{'id':'winq-stay-30'}}];calls.clear()
    retention.apply_stay_discount('cus_1');assert calls==[]                                                              # a retry does not stack it
    subs.data[1]['status']='canceled'
    with pytest.raises(RuntimeError):retention.apply_stay_discount('cus_1')                                                # nothing running: it fails loudly
