import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('CONTROL_DB_PATH',str(tmp_path/'c.db'));monkeypatch.setenv('ADMIN_TOKEN','a'*32)
    import control.app as c
    c._HITS.clear()
    return TestClient(c.app)


OK={'email':'Jan@Example.com','name':'Jan','mode':'drafts','adult':True,'terms':True}


def test_pages_render_with_brand_and_strict_csp(client):
    r=client.get('/')
    assert r.status_code==200 and 'Iskra' in r.text and '{{BRAND}}' not in r.text
    assert "script-src 'self'" in r.headers['content-security-policy']
    assert client.get('/prywatnosc').status_code==200 and client.get('/regulamin').status_code==200
    assert client.get('/assets/landing.js').status_code==200 and client.get('/assets/../app.py').status_code==404


def test_waitlist_requires_consents_and_valid_email(client):
    assert client.post('/api/waitlist',json={**OK,'adult':False}).status_code==422
    assert client.post('/api/waitlist',json={**OK,'email':'nope'}).status_code==422
    assert client.post('/api/waitlist',json=OK).json()=={'ok':True}
    client.post('/api/waitlist',json={**OK,'mode':'autopilot'})
    data=client.get('/admin/waitlist',headers={'Authorization':'Bearer '+'a'*32}).json()
    assert data['count']==1 and data['items'][0]['email']=='jan@example.com' and data['items'][0]['mode']=='autopilot'


def test_honeypot_and_admin_auth_and_rate_limit(client):
    assert client.post('/api/waitlist',json={**OK,'website':'spam'}).json()=={'ok':True}
    assert client.get('/admin/waitlist',headers={'Authorization':'Bearer '+'a'*32}).json()['count']==0
    assert client.get('/admin/waitlist').status_code==401
    for i in range(5):client.post('/api/waitlist',json={**OK,'email':f'u{i}@ex.com'})
    assert client.post('/api/waitlist',json={**OK,'email':'late@ex.com'}).status_code==429


def test_rate_limit_uses_forwarded_ip_behind_proxy(client,monkeypatch):
    monkeypatch.setenv('TRUST_PROXY','true')
    for i in range(5):client.post('/api/waitlist',json={**OK,'email':f'a{i}@ex.com'},headers={'X-Forwarded-For':'1.1.1.1'})
    assert client.post('/api/waitlist',json={**OK,'email':'x@ex.com'},headers={'X-Forwarded-For':'1.1.1.1'}).status_code==429
    assert client.post('/api/waitlist',json={**OK,'email':'y@ex.com'},headers={'X-Forwarded-For':'2.2.2.2, 10.0.0.1'}).status_code==200


REG={'email':'Ola@Example.com','password':'bardzo-tajne-haslo','name':'Ola','mode':'drafts','adult':True,'terms':True}
ADMIN={'Authorization':'Bearer '+'a'*32}


def test_register_login_logout_and_account_status(client):
    assert client.post('/api/register',json={**REG,'password':'krotkie'}).status_code==422
    r=client.post('/api/register',json=REG);assert r.status_code==200 and 'iskra_session' in r.cookies
    assert client.post('/api/register',json=REG).status_code==409
    me=client.get('/api/me').json();assert {k:me[k] for k in ('email','name','status','panel_ready','billing_enabled')}=={'email':'ola@example.com','name':'Ola','status':'pending','panel_ready':False,'billing_enabled':False}
    assert client.get('/konto/panel',follow_redirects=False).headers['location']=='/konto'
    client.post('/api/logout');client.cookies.clear()
    assert client.get('/api/me').status_code==401 and client.get('/konto',follow_redirects=False).headers['location']=='/zaloguj'
    assert client.post('/api/login',json={'email':'ola@example.com','password':'zle-haslo-123'}).status_code==401
    assert client.post('/api/login',json={'email':'OLA@example.com','password':REG['password']}).status_code==200
    assert client.get('/api/me').status_code==200


def test_admin_activation_and_sso_link_verified_by_instance(client,store,monkeypatch):
    monkeypatch.delenv('PUBLIC_ORIGIN',raising=False)  # store fixture sets it; this test exercises same-origin calls without an Origin header
    client.post('/api/register',json=REG)
    assert client.post('/admin/accounts/activate',json={'email':'ola@example.com','instance_url':'https://x.onrender.com'}).status_code==401
    bad=client.post('/admin/accounts/activate',headers=ADMIN,json={'email':'ola@example.com','instance_url':'http://x'});assert bad.status_code==422
    out=client.post('/admin/accounts/activate',headers=ADMIN,json={'email':'ola@example.com','instance_url':'https://x.onrender.com/'}).json()
    assert client.get('/api/me').json()['panel_ready'] is True
    loc=client.get('/konto/panel',follow_redirects=False).headers['location']
    assert loc.startswith('https://x.onrender.com/auth/sso?t=')
    from agent.auth import verify_sso
    token=loc.split('t=',1)[1]
    monkeypatch.setenv('SSO_SECRET',out['sso_secret'])
    assert verify_sso(token,'https://x.onrender.com')
    assert not verify_sso(token,'https://x.onrender.com')           # single use
    loc2=client.get('/konto/panel',follow_redirects=False).headers['location'].split('t=',1)[1]
    assert not verify_sso(loc2,'https://other.onrender.com')        # wrong audience
    monkeypatch.setenv('SSO_SECRET','z'*40)
    assert not verify_sso(loc2,'https://x.onrender.com')            # wrong secret
    assert client.post('/admin/accounts/status',headers=ADMIN,json={'email':'ola@example.com','status':'disabled'}).json()=={'ok':True}
    assert client.get('/api/me').status_code==401                   # sessions revoked


def test_expired_sso_token_rejected(store,monkeypatch):
    import time,base64,json,hmac,hashlib
    from agent.auth import verify_sso
    secret='s'*40;monkeypatch.setenv('SSO_SECRET',secret)
    def make(exp):
        p=base64.urlsafe_b64encode(json.dumps({'aud':'https://x.onrender.com','sub':'a','exp':exp,'n':'n'*20}).encode()).decode().rstrip('=')
        return p+'.'+base64.urlsafe_b64encode(hmac.new(secret.encode(),p.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    assert not verify_sso(make(int(time.time())-30),'https://x.onrender.com')
    assert verify_sso(make(int(time.time())+30),'https://x.onrender.com')
    monkeypatch.setenv('SSO_SECRET','short')
    assert not verify_sso(make(int(time.time())+30),'https://x.onrender.com')


def test_delete_account_requires_password(client):
    client.post('/api/register',json=REG)
    assert client.post('/api/account/delete',json={'password':'nie-to-haslo'}).status_code==401
    assert client.post('/api/account/delete',json={'password':REG['password']}).json()=={'deleted':True}
    assert client.post('/api/login',json={'email':'ola@example.com','password':REG['password']}).status_code==401


def test_cross_origin_posts_blocked_when_origin_configured(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_ORIGIN','https://iskra.example')
    assert client.post('/api/register',json=REG,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/register',json=REG,headers={'Origin':'https://iskra.example'}).status_code==200


def test_share_card_meta_and_assets(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_ORIGIN','https://iskra.example')
    html=client.get('/').text
    assert '<meta property="og:image" content="https://iskra.example/assets/og.png">' in html
    assert 'twitter:card" content="summary_large_image"' in html and '{{' not in html
    r=client.get('/assets/og.png');assert r.status_code==200 and r.headers['content-type']=='image/png' and r.content[:4]==b'\x89PNG'
    assert client.get('/assets/icon.svg').headers['content-type'].startswith('image/svg+xml')
    assert 'og:image' in client.get('/rejestracja').text


def _signed(payload,secret):
    import time,hmac,hashlib
    ts=str(int(time.time()))
    sig=hmac.new(secret.encode(),(ts+'.'+payload).encode(),hashlib.sha256).hexdigest()
    return {'Stripe-Signature':f't={ts},v1={sig}','Content-Type':'application/json'}


def test_billing_checkout_webhook_and_panel_gate(client,monkeypatch):
    import json,stripe
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_x');monkeypatch.setenv('STRIPE_PRICE_ID','price_x');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_test')
    seen={}
    class S:url='https://checkout.stripe.com/c/pay/cs_test'
    def fake_create(**kw):seen.update(kw);return S
    monkeypatch.setattr(stripe.checkout.Session,'create',staticmethod(fake_create))
    client.post('/api/register',json=REG)
    acc_id=None
    out=client.post('/api/billing/checkout',json={'start_now':True}).json();assert out['url'].startswith('https://checkout.stripe.com/')
    assert seen['mode']=='subscription' and seen['customer_email']=='ola@example.com' and seen['client_reference_id'].isdigit()
    acc_id=seen['client_reference_id']
    me=client.get('/api/me').json();assert me['has_access'] is False and me['plan_status']=='none'
    client.post('/admin/accounts/activate',headers=ADMIN,json={'email':'ola@example.com','instance_url':'https://x.onrender.com'})
    assert client.get('/konto/panel',follow_redirects=False).headers['location']=='/konto'   # paid access required
    bad=client.post('/stripe/webhook',content='{}',headers={'Stripe-Signature':'t=1,v1=00','Content-Type':'application/json'});assert bad.status_code==400
    ev=json.dumps({'id':'evt_1','object':'event','type':'checkout.session.completed','data':{'object':{'object':'checkout.session','mode':'subscription','client_reference_id':acc_id,'customer':'cus_123'}}})
    assert client.post('/stripe/webhook',content=ev,headers=_signed(ev,'whsec_test')).json()=={'received':True}
    me=client.get('/api/me').json();assert me['has_access'] and me['plan_status']=='active' and me['panel_ready'] and me['can_manage_billing']
    assert client.get('/konto/panel',follow_redirects=False).headers['location'].startswith('https://x.onrender.com/auth/sso?t=')
    assert client.post('/api/billing/checkout',json={'start_now':True}).status_code==409
    ev2=json.dumps({'id':'evt_2','object':'event','type':'customer.subscription.deleted','data':{'object':{'object':'subscription','customer':'cus_123','status':'canceled'}}})
    client.post('/stripe/webhook',content=ev2,headers=_signed(ev2,'whsec_test'))
    me=client.get('/api/me').json();assert me['plan_status']=='canceled' and not me['has_access'] and not me['panel_ready']
    class P:url='https://billing.stripe.com/p/session/x'
    monkeypatch.setattr(stripe.billing_portal.Session,'create',staticmethod(lambda **kw:P))
    assert client.post('/api/billing/portal').json()['url'].startswith('https://billing.stripe.com/')


def test_comped_account_skips_billing(client,monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_x');monkeypatch.setenv('STRIPE_PRICE_ID','price_x');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_test')
    client.post('/api/register',json=REG)
    client.post('/admin/accounts/activate',headers=ADMIN,json={'email':'ola@example.com','instance_url':'https://x.onrender.com','comped':True})
    assert client.get('/api/me').json()['panel_ready'] is True


def test_payment_link_mode_needs_no_secret_key(client,monkeypatch):
    import json
    from urllib.parse import urlparse,parse_qs
    monkeypatch.delenv('STRIPE_SECRET_KEY',raising=False);monkeypatch.delenv('STRIPE_PRICE_ID',raising=False)
    monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/test_abc');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_link')
    monkeypatch.setenv('STRIPE_PORTAL_URL','https://billing.stripe.com/p/login/test_x')
    client.post('/api/register',json=REG)
    assert client.get('/api/me').json()['billing_enabled'] is True
    url=client.post('/api/billing/checkout',json={'start_now':True}).json()['url'];qs=parse_qs(urlparse(url).query)
    assert url.startswith('https://buy.stripe.com/test_abc?') and qs['prefilled_email']==['ola@example.com'] and qs['client_reference_id'][0].isdigit()
    ev=json.dumps({'type':'checkout.session.completed','data':{'object':{'mode':'subscription','client_reference_id':qs['client_reference_id'][0],'customer':'cus_9'}}})
    client.post('/stripe/webhook',content=ev,headers=_signed(ev,'whsec_link'))
    me=client.get('/api/me').json();assert me['has_access'] and me['can_manage_billing']
    assert client.post('/api/billing/portal').json()['url'].startswith('https://billing.stripe.com/p/login/test_x?prefilled_email=')


def _render_mock(calls,fail=False):
    import httpx,json
    def handler(req):
        calls.append((req.method,req.url.path,json.loads(req.content or b'{}')))
        assert req.headers['authorization']=='Bearer rnd_test'
        if fail:return httpx.Response(500,json={'message':'boom'})
        if req.url.path=='/v1/services':return httpx.Response(201,json={'service':{'id':'srv-new','serviceDetails':{'url':'https://iskra-u1-ab12.onrender.com'}},'deployId':'dep-1'})
        return httpx.Response(200,json={})
    return httpx.MockTransport(handler)


def _provision_env(monkeypatch):
    for k,v in {'RENDER_API_KEY':'rnd_test','RENDER_OWNER_ID':'tea-x','RENDER_ENV_GROUP_ID':'evg-x','PUBLIC_ORIGIN':''}.items():monkeypatch.setenv(k,v)
    monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/t');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_p')


def test_paid_checkout_provisions_instance_once_and_cancel_suspends(client,monkeypatch):
    import json
    from control import provision,mailer
    _provision_env(monkeypatch);calls=[];monkeypatch.setattr(provision,'TRANSPORT',_render_mock(calls));mailer.SENT.clear()
    client.post('/api/register',json=REG)
    ref=client.get('/admin/accounts',headers=ADMIN).json()  # account exists
    aid=parse_id(client)
    ev=json.dumps({'type':'checkout.session.completed','data':{'object':{'mode':'subscription','client_reference_id':aid,'customer':'cus_p'}}})
    client.post('/stripe/webhook',content=ev,headers=_signed(ev,'whsec_p'))
    client.post('/stripe/webhook',content=ev,headers=_signed(ev,'whsec_p'))      # Stripe retry: no second server
    created=[c for c in calls if c[1]=='/v1/services']
    assert len(created)==1
    body=created[0][2];env={e['key']:e['value'] for e in body['envVars']}
    assert body['serviceDetails']['disk']['mountPath']=='/var/data' and body['ownerId']=='tea-x'
    assert len(env['TOKEN_ENCRYPTION_KEY'])>=43 and len(env['SSO_SECRET'])>=40 and 'ANTHROPIC_API_KEY' not in env and 'TINDER_AUTH_TOKEN' not in env
    assert ('POST','/v1/env-groups/evg-x/services/srv-new',{}) in calls and ('POST','/v1/services/srv-new/deploys',{}) in calls
    me=client.get('/api/me').json();assert me['panel_ready'] and me['provision_state']=='done'
    assert client.get('/konto/panel',follow_redirects=False).headers['location'].startswith('https://iskra-u1-ab12.onrender.com/auth/sso?t=')
    assert [m['subject'] for m in mailer.SENT]==['Witaj w Iskrze','Płatność przyjęta','Twój panel jest gotowy','Płatność przyjęta']
    ev2=json.dumps({'type':'customer.subscription.deleted','data':{'object':{'customer':'cus_p','status':'canceled'}}})
    client.post('/stripe/webhook',content=ev2,headers=_signed(ev2,'whsec_p'))
    assert calls[-1][:2]==('POST','/v1/services/srv-new/suspend')


def parse_id(client):
    from urllib.parse import urlparse,parse_qs
    return parse_qs(urlparse(client.post('/api/billing/checkout',json={'start_now':True}).json()['url']).query)['client_reference_id'][0]


def test_failed_provision_is_recorded_and_retryable(client,monkeypatch):
    import json
    from control import provision
    _provision_env(monkeypatch);calls=[];monkeypatch.setattr(provision,'TRANSPORT',_render_mock(calls,fail=True))
    client.post('/api/register',json=REG);aid=parse_id(client)
    ev=json.dumps({'type':'checkout.session.completed','data':{'object':{'mode':'subscription','client_reference_id':aid,'customer':'cus_f'}}})
    client.post('/stripe/webhook',content=ev,headers=_signed(ev,'whsec_p'))
    assert client.get('/api/me').json()['provision_state']=='failed'
    monkeypatch.setattr(provision,'TRANSPORT',_render_mock(calls))
    assert client.post('/admin/accounts/provision',headers=ADMIN,json={'email':'ola@example.com','retry':True}).json()=={'result':'done'}


def test_comped_emails_are_free_on_signup(client,monkeypatch):
    monkeypatch.setenv('COMPED_EMAILS','boss@example.com, ola@example.com');monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/t');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_p')
    client.post('/api/register',json=REG)
    me=client.get('/api/me').json();assert me['has_access'] is True and me['billing_enabled'] is True


def test_password_reset_flow(client):
    from control import mailer
    mailer.SENT.clear();client.post('/api/register',json=REG);client.cookies.clear()
    assert client.post('/api/password/forgot',json={'email':'nobody@example.com'}).json()=={'ok':True}
    assert client.post('/api/password/forgot',json={'email':'ola@example.com'}).json()=={'ok':True}
    link=[m for m in mailer.SENT if m['subject']=='Ustaw nowe hasło'][-1]['text'].split('\n')[1]
    token=link.split('t=',1)[1]
    assert client.post('/api/password/reset',json={'token':token,'password':'krotkie'}).status_code==422
    assert client.post('/api/password/reset',json={'token':token,'password':'nowe-dlugie-haslo'}).json()=={'ok':True}
    assert client.post('/api/password/reset',json={'token':token,'password':'nowe-dlugie-haslo'}).status_code==400   # single use
    client.cookies.clear()
    assert client.post('/api/login',json={'email':'ola@example.com','password':'nowe-dlugie-haslo'}).status_code==200
    assert client.get('/nie-pamietam-hasla').status_code==200 and client.get('/nowe-haslo').status_code==200


def test_checkout_requires_start_consent_and_withdrawal_within_14_days(client,monkeypatch):
    import time as _t
    from control import app as capp
    monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/test_x');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_test')
    monkeypatch.setenv('LEGAL_EMAIL','owner@example.com')
    client.post('/api/register',json={'email':'w@example.com','password':'długiehasło123','adult':True,'terms':True})
    assert client.post('/api/billing/checkout').status_code==422
    assert client.post('/api/billing/checkout',json={'start_now':True}).status_code==200
    assert capp.q('SELECT start_consent_at FROM accounts WHERE email=?',('w@example.com',),fetch=True)[0]['start_consent_at']
    assert client.post('/api/billing/withdraw',json={'confirm':True}).status_code==409  # nothing paid yet
    capp.q("UPDATE accounts SET paid_at=?, plan_status='active', stripe_customer='cus_w' WHERE email=?",(_t.time(),'w@example.com'))
    assert client.get('/api/me').json()['can_withdraw'] is True
    assert client.post('/api/billing/withdraw',json={}).status_code==422
    capp.mailer.SENT.clear()
    assert client.post('/api/billing/withdraw',json={'confirm':True}).json()=={'withdrawn':True}
    me=client.get('/api/me').json();assert me['withdrawn'] and not me['has_access'] and not me['can_withdraw']
    assert {m['to'] for m in capp.mailer.SENT}=={'w@example.com','owner@example.com'}
    capp.q("UPDATE accounts SET plan_status='withdrawn' WHERE email=?",('w@example.com',))
    capp.q("UPDATE accounts SET paid_at=? WHERE email=?",(_t.time()-15*86400,'w@example.com'))
    capp.q("UPDATE accounts SET withdrawn_at=NULL WHERE email=?",('w@example.com',))
    assert client.post('/api/billing/withdraw',json={'confirm':True}).status_code==409  # past 14 days


def test_legal_pages_fill_seller_identity(client,monkeypatch):
    monkeypatch.setenv('LEGAL_NAME','Jan Testowy')
    r=client.get('/regulamin');assert r.status_code==200 and 'Jan Testowy' in r.text and '{{' not in r.text
    assert 'Odstąpienie od umowy' in r.text and 'art. 50' in r.text
    p=client.get('/prywatnosc');assert p.status_code==200 and 'art. 9' in p.text and '{{' not in p.text


def _template_mock(calls):
    import httpx,json
    def handler(req):
        calls.append((req.method,req.url.path,json.loads(req.content or b'{}')))
        assert req.headers['authorization']=='Bearer rnd_test'
        if req.method=='GET' and req.url.path=='/v1/services/srv-tpl/env-vars':
            return httpx.Response(200,json=[{'envVar':{'key':'ANTHROPIC_API_KEY','value':'sk-ant-x'}},{'envVar':{'key':'LLM_PROVIDER','value':'anthropic'}},
                                            {'envVar':{'key':'DASHBOARD_TOKEN','value':'never-copied'}}])
        if req.method=='GET' and req.url.path=='/v1/services/srv-owner':
            return httpx.Response(200,json={'id':'srv-owner','serviceDetails':{'url':'https://owner-bot.onrender.com'}})
        if req.url.path=='/v1/services':return httpx.Response(201,json={'service':{'id':'srv-new','serviceDetails':{'url':'https://iskra-u1-ab12.onrender.com'}}})
        return httpx.Response(200,json={})
    return httpx.MockTransport(handler)


def test_provision_copies_only_model_settings_from_template(client,monkeypatch):
    import json
    from control import provision
    _provision_env(monkeypatch);monkeypatch.delenv('RENDER_ENV_GROUP_ID');monkeypatch.setenv('INSTANCE_TEMPLATE_SERVICE_ID','srv-tpl')
    calls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock(calls))
    client.post('/api/register',json=REG);aid=parse_id(client)
    ev=json.dumps({'type':'checkout.session.completed','data':{'object':{'mode':'subscription','client_reference_id':aid,'customer':'cus_t'}}})
    client.post('/stripe/webhook',content=ev,headers=_signed(ev,'whsec_p'))
    body=[c for c in calls if c[1]=='/v1/services'][0][2];env={e['key']:e['value'] for e in body['envVars']}
    assert env['ANTHROPIC_API_KEY']=='sk-ant-x' and env['LLM_PROVIDER']=='anthropic' and env['DASHBOARD_TOKEN']!='never-copied'
    assert not any('/env-groups/' in c[1] for c in calls)
    assert client.get('/api/me').json()['panel_ready']


def test_owner_account_links_existing_bot_for_free(client,monkeypatch):
    from control import provision
    _provision_env(monkeypatch);monkeypatch.setenv('OWNER_EMAIL','Owner@Example.com');monkeypatch.setenv('OWNER_SERVICE_ID','srv-owner')
    monkeypatch.setenv('PUBLIC_ORIGIN','http://testserver')
    calls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock(calls))
    r=client.post('/api/register',json={**REG,'email':'owner@example.com'},headers={'Origin':'http://testserver'});assert r.status_code==200,r.text
    me=client.get('/api/me');assert me.status_code==200,me.text;me=me.json()
    assert me['has_access'] and me['panel_ready'] and me['provision_state']=='done'
    puts={c[1]:c[2] for c in calls if c[0]=='PUT'}
    assert len(puts['/v1/services/srv-owner/env-vars/SSO_SECRET']['value'])>=40
    assert puts['/v1/services/srv-owner/env-vars/CONTROL_ORIGIN']=={'value':'http://testserver'}
    assert ('POST','/v1/services/srv-owner/deploys',{}) in calls and not any(c[1]=='/v1/services' for c in calls)
    assert client.get('/konto/panel',follow_redirects=False).headers['location'].startswith('https://owner-bot.onrender.com/auth/sso?t=')


def test_owner_registered_before_render_key_is_linked_on_next_login(client,monkeypatch):
    from control import provision
    monkeypatch.setenv('OWNER_EMAIL','owner@example.com');monkeypatch.setenv('OWNER_SERVICE_ID','srv-owner')
    client.post('/api/register',json={**REG,'email':'owner@example.com'})
    assert client.get('/api/me').json()['provision_state']=='manual'
    _provision_env(monkeypatch);calls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock(calls))
    client.post('/api/logout');client.post('/api/login',json={'email':'owner@example.com','password':REG['password']})
    assert client.get('/api/me').json()['panel_ready']
