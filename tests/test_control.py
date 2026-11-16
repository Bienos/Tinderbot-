import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('CONTROL_DB_PATH',str(tmp_path/'c.db'));monkeypatch.setenv('ADMIN_TOKEN','a'*32)
    import control.app as c
    c._HITS.clear()
    return TestClient(c.app)


def test_asset_urls_carry_content_version_so_deploys_beat_browser_cache(client):
    import re
    import control.app as c
    for path in ('/','/rejestracja','/zaloguj'):
        r=client.get(path)
        assert r.headers['cache-control']=='no-cache'
        refs=re.findall(r'/assets/([a-z]+\.(?:css|js))(\?v=[0-9a-f]+)?',r.text)
        assert refs and all(v=='?v='+c.ASSET_VERSIONS[name] for name,v in refs)
    assert client.get('/assets/landing.css?v='+c.ASSET_VERSIONS['landing.css']).status_code==200


OK={'email':'Jan@Example.com','name':'Jan','mode':'drafts','adult':True,'terms':True}


def test_pages_render_with_brand_and_strict_csp(client):
    r=client.get('/')
    assert r.status_code==200 and 'Winq' in r.text and '{{BRAND}}' not in r.text
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


def test_delete_option_is_not_on_main_account_page(client):
    assert client.get('/konto/zaawansowane',follow_redirects=False).status_code==303
    client.post('/api/register',json=REG)
    assert 'delete-form' not in client.get('/konto').text
    assert 'delete-form' in client.get('/konto/zaawansowane').text


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
    pytest.importorskip('stripe')  # only the control service installs Stripe
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
    pytest.importorskip('stripe')  # only the control service installs Stripe
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
    pytest.importorskip('stripe')  # only the control service installs Stripe
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
    assert [m['subject'] for m in mailer.SENT]==['Witaj w Winq','Płatność przyjęta','Twój panel jest gotowy','Płatność przyjęta']
    ev2=json.dumps({'type':'customer.subscription.deleted','data':{'object':{'customer':'cus_p','status':'canceled'}}})
    client.post('/stripe/webhook',content=ev2,headers=_signed(ev2,'whsec_p'))
    assert calls[-1][:2]==('POST','/v1/services/srv-new/suspend')


def parse_id(client):
    from urllib.parse import urlparse,parse_qs
    return parse_qs(urlparse(client.post('/api/billing/checkout',json={'start_now':True}).json()['url']).query)['client_reference_id'][0]


def test_failed_provision_is_recorded_and_retryable(client,monkeypatch):
    pytest.importorskip('stripe')  # only the control service installs Stripe
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
    pytest.importorskip('stripe')  # only the control service installs Stripe
    monkeypatch.setenv('COMPED_EMAILS','boss@example.com, ola@example.com');monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/t');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_p')
    client.post('/api/register',json=REG)
    me=client.get('/api/me').json();assert me['has_access'] is True and me['billing_enabled'] is True


def test_password_reset_flow(client):
    from control import mailer
    mailer.SENT.clear();client.post('/api/register',json=REG);client.cookies.clear()
    r=client.post('/api/password/forgot',json={'email':'nobody@example.com'})
    assert r.status_code==404 and 'Nie ma konta' in r.json()['detail'] and not [m for m in mailer.SENT if m['subject']=='Ustaw nowe hasło']
    assert client.post('/api/password/forgot',json={'email':'ola@example.com'}).json()=={'ok':True}
    import re
    token=re.search(r'nowe-haslo\?t=([\w-]+)',[m for m in mailer.SENT if m['subject']=='Ustaw nowe hasło'][-1]['text']).group(1)
    assert client.post('/api/password/reset',json={'token':token,'password':'krotkie'}).status_code==422
    assert client.post('/api/password/reset',json={'token':token,'password':'nowe-dlugie-haslo'}).json()=={'ok':True}
    assert client.post('/api/password/reset',json={'token':token,'password':'nowe-dlugie-haslo'}).status_code==400   # single use
    client.cookies.clear()
    assert client.post('/api/login',json={'email':'ola@example.com','password':'nowe-dlugie-haslo'}).status_code==200
    assert client.get('/nie-pamietam-hasla').status_code==200 and client.get('/nowe-haslo').status_code==200


def test_checkout_requires_start_consent_and_withdrawal_within_14_days(client,monkeypatch):
    pytest.importorskip('stripe')  # only the control service installs Stripe
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
    pytest.importorskip('stripe')  # only the control service installs Stripe
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
    # OWNER_PANEL_URL puts the owner's panel on the brand's domain, and the sign-in token is issued for that address
    import base64,json as _j
    monkeypatch.setenv('OWNER_PANEL_URL','https://panel.example.com/')
    loc=client.get('/konto/panel',follow_redirects=False).headers['location']
    assert loc.startswith('https://panel.example.com/auth/sso?t=')
    payload=_j.loads(base64.urlsafe_b64decode(loc.split('t=',1)[1].split('.')[0]+'=='))
    assert payload['aud']=='https://panel.example.com'
    monkeypatch.setenv('OWNER_PANEL_URL','http://insecure.example.com')   # only https is accepted
    assert client.get('/konto/panel',follow_redirects=False).headers['location'].startswith('https://owner-bot.onrender.com/')


def test_owner_registered_before_render_key_is_linked_on_next_login(client,monkeypatch):
    from control import provision
    monkeypatch.setenv('OWNER_EMAIL','owner@example.com');monkeypatch.setenv('OWNER_SERVICE_ID','srv-owner')
    client.post('/api/register',json={**REG,'email':'owner@example.com'})
    assert client.get('/api/me').json()['provision_state']=='manual'
    _provision_env(monkeypatch);calls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock(calls))
    client.post('/api/logout');client.post('/api/login',json={'email':'owner@example.com','password':REG['password']})
    assert client.get('/api/me').json()['panel_ready']


def test_setup_progress_follows_the_real_render_deploy(client,monkeypatch):
    import httpx,json
    from control import provision
    import control.app as capp
    _provision_env(monkeypatch);monkeypatch.setenv('OWNER_EMAIL','owner@example.com');monkeypatch.setenv('OWNER_SERVICE_ID','srv-owner')
    status={'now':'build_in_progress'};capp._DEPLOY_CACHE.clear()
    def handler(req):
        if req.method=='GET' and req.url.path=='/v1/services/srv-owner/deploys':
            return httpx.Response(200,json=[{'deploy':{'id':'dep-1','status':status['now']},'cursor':'c'}])
        if req.method=='GET' and req.url.path=='/v1/services/srv-owner':
            return httpx.Response(200,json={'id':'srv-owner','serviceDetails':{'url':'https://owner-bot.onrender.com'}})
        return httpx.Response(200,json={})
    monkeypatch.setattr(provision,'TRANSPORT',httpx.MockTransport(handler))
    client.post('/api/register',json={**REG,'email':'owner@example.com'})
    setup=client.get('/api/me').json()['setup']
    assert setup['stage']=='building' and setup['kind']=='link' and setup['expected']==120 and 0<=setup['elapsed']<5
    for render,stage in (('update_in_progress','starting'),('live','ready'),('update_failed','slow')):
        status['now']=render;capp._DEPLOY_CACHE.clear()
        assert client.get('/api/me').json()['setup']['stage']==stage


def test_setup_progress_without_render_access_never_pretends_to_build(client,monkeypatch):
    client.post('/api/register',json={**REG,'email':'plain@example.com'})
    assert client.get('/api/me').json()['setup']['stage']=='queued'
    monkeypatch.setenv('OWNER_EMAIL','owner@example.com');monkeypatch.setenv('OWNER_SERVICE_ID','srv-owner')
    client.post('/api/logout');client.post('/api/register',json={**REG,'email':'owner@example.com'})
    assert client.get('/api/me').json()['setup']['stage']=='manual'


def test_landing_seo_head_canonical_structured_data_and_no_third_party_fonts(client,monkeypatch):
    import json,re
    monkeypatch.setenv('PUBLIC_ORIGIN','https://iskra.example');monkeypatch.setenv('PLAN_PRICE','49 zł / mies.')
    html=client.get('/').text
    assert '<link rel="canonical" href="https://iskra.example/">' in html
    assert '<title>Winq, asystent randkowy AI do odpowiedzi na Tinderze</title>' in html and 'noindex' not in html
    assert 'fonts.googleapis.com' not in html and 'fonts.gstatic.com' not in html
    assert "googleapis" not in client.get('/').headers['content-security-policy']
    block=re.search(r'<script type="application/ld\+json">(.*?)</script>',html,re.S).group(1)
    graph={n['@type']:n for n in json.loads(block)['@graph']}
    assert set(graph)=={'Organization','WebSite','WebApplication','FAQPage'}
    offer=graph['WebApplication']['offers'];assert offer['price']=='49.00' and offer['priceCurrency']=='PLN'
    assert 'aggregateRating' not in json.dumps(graph)                       # never invent reviews
    shown=re.findall(r'<details><summary>(.*?)</summary>',html)
    assert [q['name'] for q in graph['FAQPage']['mainEntity']]==[re.sub(r'<[^>]+>','',s) for s in shown]  # schema = page
    assert any('49 zł' in q['acceptedAnswer']['text'] for q in graph['FAQPage']['mainEntity'])


def test_old_render_address_sends_page_visits_to_the_custom_domain(client,monkeypatch):
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME','old-site.onrender.com')
    monkeypatch.setenv('PUBLIC_ORIGIN','https://old-site.onrender.com')        # before the switch: nothing moves
    assert client.get('/',headers={'host':'old-site.onrender.com'},follow_redirects=False).status_code==200
    monkeypatch.setenv('PUBLIC_ORIGIN','https://winq.example')
    r=client.get('/konto?platnosc=ok',headers={'host':'old-site.onrender.com'},follow_redirects=False)
    assert r.status_code==301 and r.headers['location']=='https://winq.example/konto?platnosc=ok'
    for path in ('/health','/api/me','/admin/accounts'):                       # machines keep the old address
        assert client.get(path,headers={'host':'old-site.onrender.com'},follow_redirects=False).status_code!=301,path
    # The webhook path is exempt; a GET (405) checks that without importing stripe, which the bot's build lacks.
    assert client.get('/stripe/webhook',headers={'host':'old-site.onrender.com'},follow_redirects=False).status_code!=301
    assert client.get('/',follow_redirects=False).status_code==200                  # the new domain itself is served


def test_account_pages_are_noindex_and_legal_pages_are_indexable_with_own_canonical(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_ORIGIN','https://iskra.example')
    for path in ('/zaloguj','/rejestracja','/nie-pamietam-hasla'):
        h=client.get(path).text
        assert '<meta name="robots" content="noindex,follow">' in h and f'<link rel="canonical" href="https://iskra.example{path}">' in h
    for path in ('/regulamin','/prywatnosc'):
        h=client.get(path).text
        assert 'noindex' not in h and f'<link rel="canonical" href="https://iskra.example{path}">' in h
        assert 'application/ld+json' not in h


def test_robots_sitemap_and_llms_txt(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_ORIGIN','https://iskra.example');monkeypatch.setenv('PLAN_PRICE','49 zł / mies.')
    robots=client.get('/robots.txt').text
    assert 'User-agent: *\nAllow: /' in robots and 'Disallow: /api/' in robots and 'Sitemap: https://iskra.example/sitemap.xml' in robots
    assert 'Disallow: /zaloguj' not in robots and 'Disallow: /rejestracja' not in robots   # noindex must stay visible to crawlers
    sm=client.get('/sitemap.xml');assert sm.headers['content-type'].startswith('application/xml')
    assert sm.text.count('<url>')==3 and '<loc>https://iskra.example/</loc>' in sm.text and 'zaloguj' not in sm.text
    llms=client.get('/llms.txt').text
    assert llms.startswith('# Winq') and '49 zł / mies.' in llms and 'nie jest powiązany z Tinder' in llms


def test_fonts_are_served_from_here_with_long_cache_and_unknown_names_404(client):
    r=client.get('/assets/fonts/unbounded-latin-ext-v1.woff2')
    assert r.status_code==200 and r.content[:4]==b'wOF2' and 'immutable' in r.headers['cache-control']
    assert r.headers['content-type']=='font/woff2'
    assert client.get('/assets/fonts/../app.py').status_code in (404,422) and client.get('/assets/fonts/evil.woff2').status_code==404
    css=client.get('/assets/landing.css').text
    assert css.count('@font-face')==4 and 'gstatic' not in css and 'font-display:swap' in css


def _fly_env(monkeypatch):
    _provision_env(monkeypatch)
    monkeypatch.delenv('RENDER_ENV_GROUP_ID',raising=False);monkeypatch.setenv('INSTANCE_TEMPLATE_SERVICE_ID','srv-tpl')
    for k,v in {'PROVISION_BACKEND':'fly','FLY_API_TOKEN':'FlyV1 fm2_test','FLY_ORG':'personal',
                'FLY_IMAGE':'registry.fly.io/iskra-img:latest','PUBLIC_ORIGIN':'http://testserver'}.items():monkeypatch.setenv(k,v)


def _fly_mock(calls,fail_machine=False,machine_state='started',checks=('passing',),cert_status='Ready',fail_cert=False):
    import httpx,json
    def handler(req):
        body=json.loads(req.content or b'{}')
        calls.append((req.method,req.url.path,body,req.headers.get('authorization')))
        p=req.url.path
        if req.method=='POST' and p=='/v1/apps':return httpx.Response(201,json={'id':body['name']})
        if p.endswith('/certificates/acme'):return httpx.Response(500,json={'error':'nope'}) if fail_cert else httpx.Response(200,json={'hostname':body['hostname']})
        if '/certificates/' in p and req.method=='GET':return httpx.Response(200,json={'status':cert_status})
        if '/certificates/' in p and req.method=='DELETE':return httpx.Response(200,json={})
        if p.endswith('/ip_assignments'):return httpx.Response(200,json={'ip':'1.2.3.4','shared':True})
        if p.endswith('/secrets'):return httpx.Response(200,json={'version':3,'secrets':[]})
        if p.endswith('/volumes'):return httpx.Response(200,json={'id':'vol_123','name':'data','region':'fra','state':'created'})
        if req.method=='POST' and p.endswith('/machines'):
            return httpx.Response(500,json={'error':'capacity'}) if fail_machine else httpx.Response(200,json={'id':'m_1','state':'created'})
        if p.endswith('/wait'):return httpx.Response(200,json={'ok':True})
        if req.method=='GET' and p.endswith('/machines'):
            return httpx.Response(200,json=[{'id':'m_1','state':machine_state,'version':'v1','checks':[{'status':s} for s in checks],
                'config':{'image':'registry.fly.io/iskra-img:old','services':[{'autostart':True}],'mounts':[{'volume':'vol_123','path':'/var/data'}]}}])
        return httpx.Response(200,json={'ok':True})
    return httpx.MockTransport(handler)


def test_fly_provisioning_builds_an_isolated_always_on_bot_with_secrets_outside_the_config(client,monkeypatch):
    from control import provision,fly
    import control.app as capp
    _fly_env(monkeypatch)
    rcalls=[];fcalls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock(rcalls));monkeypatch.setattr(fly,'TRANSPORT',_fly_mock(fcalls))
    assert provision.enabled()
    client.post('/api/register',json=REG,headers={'Origin':'http://testserver'});acc=capp.q('SELECT id FROM accounts',fetch=True)[0]
    assert capp.run_provision(acc['id'])=='done'
    row=capp.q('SELECT * FROM accounts WHERE id=?',(acc['id'],),fetch=True)[0]
    app=row['render_service_id'][4:]
    assert row['render_service_id'].startswith('fly:winq-u') and row['instance_url']==f'https://{app}.fly.dev'
    steps=[(m,p.replace(app,'APP')) for m,p,_,_ in fcalls]
    assert steps[:7]==[('POST','/v1/apps'),('POST','/v1/apps/APP/ip_assignments'),('POST','/v1/apps/APP/ip_assignments'),
                       ('POST','/v1/apps/APP/secrets'),('POST','/v1/apps/APP/volumes'),('POST','/v1/apps/APP/machines'),
                       ('GET','/v1/apps/APP/machines/m_1/wait')]
    assert all(c[3]=='FlyV1 fm2_test' for c in fcalls)
    assert [c[2]['type'] for c in fcalls if c[1].endswith('ip_assignments')]==['shared_v4','v6']
    hidden=next(c[2]['values'] for c in fcalls if c[1].endswith('/secrets'))
    assert set(hidden)=={'DASHBOARD_TOKEN','TOKEN_ENCRYPTION_KEY','SSO_SECRET','ANTHROPIC_API_KEY'} and hidden['ANTHROPIC_API_KEY']=='sk-ant-x'
    assert hidden['SSO_SECRET']==row['sso_secret']
    machine=next(c[2] for c in fcalls if c[0]=='POST' and c[1].endswith('/machines'))
    cfg=machine['config'];env=cfg['env']
    assert machine['min_secrets_version']==3 and machine['region']=='fra'
    assert not set(env)&set(fly.SECRET_KEYS)                                  # secrets never in the machine config
    assert env['PUBLIC_ORIGIN']==f'https://{app}.fly.dev' and env['CONTROL_ORIGIN']=='http://testserver' and env['AGENT_DB_PATH']=='/var/data/agent.db'
    assert cfg['mounts']==[{'volume':'vol_123','path':'/var/data'}] and cfg['guest']['memory_mb']==256
    assert cfg['init']=={'swap_size_mb':512}
    assert cfg['services'][0]['autostop']=='off' and cfg['restart']['policy']=='always' and cfg['image']=='registry.fly.io/iskra-img:latest'
    assert cfg['checks']['health']['headers']==[{'name':'Host','values':[f'{app}.fly.dev']}]   # the bot rejects other Host headers
    assert 'DASHBOARD_TOKEN' not in str(rcalls)                               # nothing written back to Render


def test_fly_failure_cleans_up_and_is_retryable(client,monkeypatch):
    from control import provision,fly
    import control.app as capp
    _fly_env(monkeypatch)
    fcalls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock([]));monkeypatch.setattr(fly,'TRANSPORT',_fly_mock(fcalls,fail_machine=True))
    client.post('/api/register',json=REG,headers={'Origin':'http://testserver'});acc=capp.q('SELECT id FROM accounts',fetch=True)[0]
    assert capp.run_provision(acc['id'])=='failed'
    assert any(m=='DELETE' and p.startswith('/v1/apps/winq-u') for m,p,_,_ in fcalls)    # no half-made app left behind
    row=capp.q('SELECT provision_state,provision_error,render_service_id FROM accounts',fetch=True)[0]
    assert row['provision_state']=='failed' and 'create machine' in row['provision_error'] and not row['render_service_id']


def test_fly_suspend_keeps_the_bot_stopped_and_resume_starts_it(monkeypatch):
    from control import fly
    monkeypatch.setenv('FLY_API_TOKEN','fm2_plain')
    calls=[];monkeypatch.setattr(fly,'TRANSPORT',_fly_mock(calls))
    from control import provision
    provision.set_suspended('fly:iskra-u7-abc',True)
    update=next(c for c in calls if c[0]=='POST' and c[1]=='/v1/apps/iskra-u7-abc/machines/m_1')
    assert update[2]['skip_launch'] is True and update[2]['config']['services']==[]   # nothing for the proxy to wake
    assert update[2]['config']['restart']=={'policy':'no'}                    # 'always' would undo the stop
    assert update[2]['config']['mounts']==[{'volume':'vol_123','path':'/var/data'}] and update[2]['current_version']=='v1'
    assert ('POST','/v1/apps/iskra-u7-abc/machines/m_1/stop') in [(c[0],c[1]) for c in calls] and calls[0][3]=='Bearer fm2_plain'
    calls.clear();provision.set_suspended('fly:iskra-u7-abc',False)
    update=next(c for c in calls if c[0]=='POST' and c[1]=='/v1/apps/iskra-u7-abc/machines/m_1')
    assert update[2]['skip_launch'] is False and update[2]['config']['services']==fly.public_services()
    assert update[2]['config']['restart']=={'policy':'always'}
    assert not any(c[1].endswith('/stop') for c in calls)


def test_fly_machine_state_drives_the_setup_progress(client,monkeypatch):
    from control import fly
    monkeypatch.setenv('FLY_API_TOKEN','fm2_plain')
    for state,checks,expected in (('created',(),'created'),('starting',(),'update_in_progress'),('started',('critical',),'update_in_progress'),
                                  ('started',('passing',),'live'),('failed',(),'update_failed')):
        monkeypatch.setattr(fly,'TRANSPORT',_fly_mock([],machine_state=state,checks=checks))
        assert fly.deploy_status('iskra-u1-abc')==expected,(state,checks)


def test_admin_rolls_only_fly_bots_to_a_new_image(client,monkeypatch):
    from control import fly
    import control.app as capp
    monkeypatch.setenv('FLY_API_TOKEN','fm2_plain');monkeypatch.setenv('FLY_IMAGE','registry.fly.io/iskra-img:latest')
    calls=[];monkeypatch.setattr(fly,'TRANSPORT',_fly_mock(calls))
    for i,sid in enumerate(('fly:iskra-u1-aaa','srv-render-1',None,'fly:iskra-u4-ddd')):
        client.post('/api/register',json={**REG,'email':f'u{i}@example.com'})
        capp.q('UPDATE accounts SET render_service_id=? WHERE email=?',(sid,f'u{i}@example.com'))
    real=fly.update_all;monkeypatch.setattr(fly,'update_all',lambda apps,image:real(apps,image,pause=0))
    assert client.post('/admin/fly/update-image',json={}).status_code==401
    r=client.post('/admin/fly/update-image',json={'image':'registry.fly.io/iskra-img:git-abc'},headers=ADMIN)
    assert r.json()=={'updating':2,'image':'registry.fly.io/iskra-img:git-abc'}
    updates=[c for c in calls if c[0]=='POST' and c[1].endswith('/machines/m_1')]
    assert {c[1].split('/')[3] for c in updates}=={'iskra-u1-aaa','iskra-u4-ddd'} and all(c[2]['config']['image']=='registry.fly.io/iskra-img:git-abc' for c in updates)
    assert all(c[2]['config']['mounts'] for c in updates)                        # data volume stays attached
    assert client.post('/admin/fly/update-image',json={'image':'docker.io/evil/img'},headers=ADMIN).status_code==422


def test_fly_with_own_domain_gives_a_private_bot_behind_the_front_door(client,monkeypatch):
    import re
    from control import provision,fly
    import control.app as capp
    _fly_env(monkeypatch);monkeypatch.setenv('FLY_PUBLIC_DOMAIN','app.winq.site')
    fcalls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock([]));monkeypatch.setattr(fly,'TRANSPORT',_fly_mock(fcalls))
    client.post('/api/register',json=REG,headers={'Origin':'http://testserver'});acc=capp.q('SELECT id FROM accounts',fetch=True)[0]
    assert capp.run_provision(acc['id'])=='done'
    row=capp.q('SELECT * FROM accounts WHERE id=?',(acc['id'],),fetch=True)[0]
    m=re.fullmatch(r'fly:winq-b-([0-9a-f]{8})',row['render_service_id']);assert m,row['render_service_id']
    bot=m.group(1)
    assert row['instance_url']==f'https://{bot}.app.winq.site'                 # what the router maps back to winq-b-<id>
    assert f"u{acc['id']}-" not in row['render_service_id']                   # no customer number in the name or address
    assert not any(p.endswith('ip_assignments') for _,p,_,_ in fcalls)         # no public address for the bot
    cert=[c for c in fcalls if c[1].endswith('/certificates/acme')]
    assert [(c[1],c[2]) for c in cert]==[('/v1/apps/winq-router/certificates/acme',{'hostname':f'{bot}.app.winq.site'})]  # one certificate per customer
    cfg=next(c[2] for c in fcalls if c[0]=='POST' and c[1].endswith('/machines'))['config']
    assert cfg['env']['PUBLIC_ORIGIN']==f'https://{bot}.app.winq.site'
    assert cfg['checks']['health']['headers']==[{'name':'Host','values':[f'{bot}.app.winq.site']}]
    import sys;from pathlib import Path
    sys.path.insert(0,str(Path(capp.__file__).resolve().parent.parent/'deploy'/'router'))
    monkeypatch.setenv('PUBLIC_DOMAIN','app.winq.site');import importlib,router;importlib.reload(router)
    assert router.BOT_ID.match(bot) and router.PREFIX=='winq-b-'                # router and provisioning agree
    sys.path.pop(0)


def test_fly_certificate_failure_removes_the_bot_and_its_certificate(client,monkeypatch):
    from control import provision,fly
    import control.app as capp
    _fly_env(monkeypatch);monkeypatch.setenv('FLY_PUBLIC_DOMAIN','app.winq.site')
    fcalls=[];monkeypatch.setattr(provision,'TRANSPORT',_template_mock([]));monkeypatch.setattr(fly,'TRANSPORT',_fly_mock(fcalls,fail_cert=True))
    client.post('/api/register',json=REG,headers={'Origin':'http://testserver'});acc=capp.q('SELECT id FROM accounts',fetch=True)[0]
    assert capp.run_provision(acc['id'])=='failed'
    deletes=[p for m,p,_,_ in fcalls if m=='DELETE']
    assert any(p.startswith('/v1/apps/winq-b-') for p in deletes) and any('/certificates/' in p for p in deletes)


def test_fly_bot_is_live_only_when_its_certificate_is_ready(monkeypatch):
    from control import fly
    monkeypatch.setenv('FLY_API_TOKEN','fm2_plain');monkeypatch.setenv('FLY_PUBLIC_DOMAIN','app.winq.site')
    for cert,expected in (('Awaiting certificates','update_in_progress'),('Awaiting configuration','update_in_progress'),('Ready','live')):
        monkeypatch.setattr(fly,'TRANSPORT',_fly_mock([],cert_status=cert))
        assert fly.deploy_status('winq-b-c611469f')==expected,cert
    monkeypatch.setattr(fly,'TRANSPORT',_fly_mock([],cert_status='Awaiting certificates'))
    assert fly.deploy_status('winq-u7-abc123')=='live'          # a bot with its own fly.dev address needs no certificate
    assert fly.bot_host('winq-b-c611469f')=='c611469f.app.winq.site' and fly.bot_host('winq-u7-abc123') is None


def test_demo_serves_real_panel_on_fake_data(client):
    page = client.get('/demo')
    assert page.status_code == 200 and 'noindex' in page.text and 'Demo na fikcyjnych danych' in page.text
    # demo.js must run before dashboard.js so the panel's API calls are answered in the browser
    assert page.text.index('/demo/static/demo.js') < page.text.index('/demo/static/dashboard.js')
    assert '"/static/' not in page.text
    for name in ('demo.js', 'dashboard.js', 'icon.svg', 'fonts/fonts.css', 'fonts/onest-latin-wght-normal.woff2'):
        assert client.get('/demo/static/' + name).status_code == 200
    for name in ('../app.py', 'fonts/../../app.py', 'dashboard.html', 'login.js'):
        assert client.get('/demo/static/' + name).status_code == 404


def test_register_stores_optional_signup_source(client):
    import control.app as c
    base={'email':'src@example.com','password':'x'*12,'adult':True,'terms':True}
    assert client.post('/api/register',json={**base,'source':'tiktok'}).status_code==200
    assert client.post('/api/register',json={**base,'email':'src2@example.com','source':'<script>'}).status_code==200
    rows={r['email']:r['source'] for r in c.q('SELECT email,source FROM accounts',fetch=True)}
    assert rows['src@example.com']=='tiktok' and rows['src2@example.com'] is None


def test_every_customer_mail_has_html_text_footer_and_no_placeholders(monkeypatch):
    from control import mailer
    monkeypatch.setenv('PUBLIC_ORIGIN','https://winq.site');monkeypatch.setenv('MAIL_FROM','kontakt@winq.site')
    monkeypatch.setenv('LEGAL_NAME','Jan Kowalski');monkeypatch.setenv('LEGAL_ADDRESS','ul. Testowa 1, 00-001 Warszawa');monkeypatch.setenv('LEGAL_ID','NIP 1234567890')
    mailer.SENT.clear();o='https://winq.site'
    mailer.welcome('a@b.pl',o);mailer.payment_ok('a@b.pl',o);mailer.panel_ready('a@b.pl',o);mailer.password_reset('a@b.pl',o+'/nowe-haslo?t=abc')
    mailer.password_changed('a@b.pl',o);mailer.payment_failed('a@b.pl',o);mailer.subscription_canceled('a@b.pl',o)
    mailer.withdrawal_confirmed('a@b.pl',o);mailer.account_deleted('a@b.pl')
    assert len(mailer.SENT)==9 and len({m['subject'] for m in mailer.SENT})==9
    for m in mailer.SENT:
        assert '<table' in m['html'] and 'kontakt@winq.site' in m['html'] and 'kontakt@winq.site' in m['text']
        assert 'Jan Kowalski' in m['html'] and 'NIP 1234567890' in m['text']
        assert 'https://winq.site/regulamin' in m['html'] and 'https://winq.site/prywatnosc' in m['text']
        assert '{{' not in m['html'] and '[adres]' not in m['html'] and 'None' not in m['text']
    reset=[m for m in mailer.SENT if m['subject']=='Ustaw nowe hasło'][0]
    assert 'href="https://winq.site/nowe-haslo?t=abc"' in reset['html'] and 'https://winq.site/nowe-haslo?t=abc' in reset['text']


def test_mail_escapes_html_and_skips_unfilled_seller_fields(monkeypatch):
    from control import mailer
    monkeypatch.setenv('PUBLIC_ORIGIN','https://winq.site');monkeypatch.setenv('LEGAL_NAME','[imię i nazwisko lub firma]');monkeypatch.delenv('LEGAL_ADDRESS',raising=False)
    mailer.SENT.clear();mailer.safe_send('o@b.pl','Test <b>','Klient <script>alert(1)</script> odstąpił')
    m=mailer.SENT[0]
    assert '<script>' not in m['html'] and '&lt;script&gt;' in m['html'] and '[imię' not in m['html']


def test_mail_goes_out_as_html_with_reply_to(monkeypatch):
    from control import mailer
    sent=[]
    class FakeSMTP:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def starttls(self,**k):pass
        def login(self,*a):pass
        def send_message(self,msg):sent.append(msg)
    monkeypatch.setattr(mailer.smtplib,'SMTP',FakeSMTP)
    for k,v in {'SMTP_HOST':'smtp.example.com','SMTP_USERNAME':'u','SMTP_PASSWORD':'p','MAIL_FROM':'kontakt@winq.site','PUBLIC_ORIGIN':'https://winq.site'}.items():monkeypatch.setenv(k,v)
    assert mailer.send_spec('x@y.pl',{'subject':'S','heading':'H','paragraphs':['p']}) is True
    msg=sent[0]
    assert msg['From']=='Winq <kontakt@winq.site>' and msg['Reply-To']=='kontakt@winq.site'
    assert msg.get_body(('plain',)) is not None and msg.get_body(('html',)) is not None


def test_state_change_mails_from_stripe_events_are_sent_once(client,monkeypatch):
    pytest.importorskip('stripe')
    import json as _j
    from control import app as capp,mailer
    class Ev:
        @staticmethod
        def construct_event(*a,**k):return {}
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_t');monkeypatch.setattr('stripe.Webhook',Ev)
    client.post('/api/register',json=REG)
    capp.q("UPDATE accounts SET stripe_customer='cus_1', plan_status='active' WHERE email=?",(REG['email'].lower(),))
    mailer.SENT.clear()
    def event(kind,status):
        return client.post('/stripe/webhook',content=_j.dumps({'type':kind,'data':{'object':{'customer':'cus_1','status':status}}}),headers={'stripe-signature':'x'})
    assert event('customer.subscription.updated','past_due').status_code==200
    assert event('customer.subscription.updated','past_due').status_code==200   # Stripe repeats events
    assert event('customer.subscription.deleted','canceled').status_code==200
    subjects=[m['subject'] for m in mailer.SENT]
    assert subjects==['Nie udało się pobrać płatności','Subskrypcja została anulowana'],subjects


def test_mail_never_leaves_from_a_private_or_foreign_address(monkeypatch):
    """MAIL_FROM must be on the site's domain and Gmail is refused (it rewrites From). Otherwise nothing is sent."""
    from control import mailer
    sent=[]
    class FakeSMTP:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def starttls(self,**k):pass
        def login(self,*a):pass
        def send_message(self,msg):sent.append(msg)
    monkeypatch.setattr(mailer.smtplib,'SMTP',FakeSMTP)
    base={'SMTP_HOST':'smtp.example.com','SMTP_USERNAME':'u','SMTP_PASSWORD':'p','PUBLIC_ORIGIN':'https://winq.site'}
    for k,v in base.items():monkeypatch.setenv(k,v)
    spec={'subject':'S','heading':'H','paragraphs':['p']}
    for bad in ('patcich98@gmail.com','','kontakt@winq.site.evil.com','kontakt@other.pl'):
        monkeypatch.setenv('MAIL_FROM',bad);assert mailer.send_spec('x@y.pl',spec) is False
    monkeypatch.setenv('MAIL_FROM','kontakt@winq.site');monkeypatch.setenv('SMTP_HOST','smtp.gmail.com')
    assert mailer.send_spec('x@y.pl',spec) is False and 'Gmail' in mailer.sender_problem()
    assert not sent
    monkeypatch.setenv('SMTP_HOST','smtp.example.com');monkeypatch.setenv('MAIL_REPLY_TO','patcich98@gmail.com')
    assert mailer.send_spec('x@y.pl',spec) is True
    assert sent[0]['From']=='Winq <kontakt@winq.site>' and sent[0]['Reply-To']=='kontakt@winq.site'   # a private Reply-To is ignored
    assert 'patcich98' not in sent[0].as_string()


def test_email_logo_is_served_for_mails(client):
    r=client.get('/assets/email-logo.png');assert r.status_code==200 and r.headers['content-type']=='image/png'


def test_free_trial_wording_follows_trial_days(client,monkeypatch):
    from control import mailer
    monkeypatch.delenv('TRIAL_DAYS',raising=False);monkeypatch.setenv('PLAN_PRICE','49 zł / mies.')
    plain=client.get('/').text
    assert 'za darmo, potem' not in plain and '{{TRIAL' not in plain
    monkeypatch.setenv('TRIAL_DAYS','3')
    page=client.get('/').text
    assert 'Pierwsze 3 dni za darmo, potem 49 zł / mies.' in page and '{{TRIAL' not in page and 'nic nie zapłacisz' in page
    terms=client.get('/regulamin').text
    assert 'Okres próbny: pierwsze 3 dni' in terms and '{{TRIAL' not in terms
    assert client.get('/rejestracja').status_code==200
    client.post('/api/register',json=REG)
    assert client.get('/api/me').json()['trial_days']==3
    mailer.SENT.clear();o='https://winq.site'
    mailer.payment_ok('a@b.pl',o);mailer.welcome('a@b.pl',o)
    assert mailer.SENT[0]['subject']=='Okres próbny rozpoczęty' and '3 dni za darmo' in mailer.SENT[0]['text'] and 'nic z niej nie pobraliśmy' in mailer.SENT[0]['text']
    assert 'Zacznij 3 dni za darmo' in mailer.SENT[1]['text']
    monkeypatch.setenv('TRIAL_DAYS','0');mailer.SENT.clear();mailer.payment_ok('a@b.pl',o)
    assert mailer.SENT[0]['subject']=='Płatność przyjęta'


PLAN_LINKS={'STRIPE_LINK_WINQ':'https://buy.stripe.com/w','STRIPE_LINK_FLIRT':'https://buy.stripe.com/f','STRIPE_LINK_CASANOVA':'https://buy.stripe.com/c'}


def test_landing_shows_three_plans_only_when_all_payment_links_exist(client,monkeypatch):
    monkeypatch.setenv('PLAN_PRICE','49 zł / mies.');monkeypatch.setenv('TRIAL_DAYS','3')
    for k in PLAN_LINKS:monkeypatch.delenv(k,raising=False)
    old=client.get('/').text
    assert 'class="ticket"' in old and 'class="tiers"' not in old and 'Jeden plan w subskrypcji, 49 zł / mies.' in old
    monkeypatch.setenv('STRIPE_LINK_WINQ','https://buy.stripe.com/w');monkeypatch.setenv('STRIPE_LINK_FLIRT','https://buy.stripe.com/f')
    assert 'class="tiers"' not in client.get('/').text            # two of three is not enough
    for k,v in PLAN_LINKS.items():monkeypatch.setenv(k,v)
    page=client.get('/').text
    assert 'class="tiers"' in page and 'class="ticket"' not in page and '{{' not in page
    for needle in ('Winq</h3>','Flirt</h3>','Casanova</h3>','19 zł','69 zł','169 zł','Najczęściej wybierany','Do 10 aktywnych rozmów','Pierwsze 3 dni w każdym pakiecie za darmo','href="/rejestracja?plan=flirt"'):
        assert needle in page,needle
    assert 'Trzy pakiety: Winq 19 zł, Flirt 69 zł, Casanova 169 zł miesięcznie.' in page and 'Jeden plan w subskrypcji' not in page
    terms=client.get('/regulamin').text
    assert 'zależy od wybranego pakietu' in terms and 'Aktywna rozmowa to rozmowa' in terms and '{{' not in terms


def test_plan_chosen_at_checkout_is_stored_and_reaches_the_new_bot(client,monkeypatch):
    pytest.importorskip('stripe')
    import json
    from control import provision
    from urllib.parse import urlparse,parse_qs
    _provision_env(monkeypatch);calls=[];monkeypatch.setattr(provision,'TRANSPORT',_render_mock(calls))
    for k,v in PLAN_LINKS.items():monkeypatch.setenv(k,v)
    client.post('/api/register',json=REG)
    me=client.get('/api/me').json();assert [p['slug'] for p in me['plans']]==['winq','flirt','casanova'] and me['plans'][1]['popular']
    assert client.post('/api/billing/checkout',json={'start_now':True}).status_code==422                      # a plan must be chosen
    assert client.post('/api/billing/checkout',json={'start_now':True,'plan':'vip'}).status_code==422
    url=client.post('/api/billing/checkout',json={'start_now':True,'plan':'flirt'}).json()['url']
    assert url.startswith('https://buy.stripe.com/f?');aid=parse_qs(urlparse(url).query)['client_reference_id'][0]
    ev=json.dumps({'type':'checkout.session.completed','data':{'object':{'mode':'subscription','client_reference_id':aid,'customer':'cus_pl'}}})
    client.post('/stripe/webhook',content=ev,headers=_signed(ev,'whsec_p'))
    assert client.get('/api/me').json()['plan']=='flirt'
    created=[c for c in calls if c[1]=='/v1/services'];assert len(created)==1
    assert {e['key']:e['value'] for e in created[0][2]['envVars']}['PLAN']=='flirt'


def test_coming_back_with_another_plan_updates_the_running_bot(client,monkeypatch):
    pytest.importorskip('stripe')
    import json
    from control import provision
    _provision_env(monkeypatch);calls=[];monkeypatch.setattr(provision,'TRANSPORT',_render_mock(calls))
    for k,v in PLAN_LINKS.items():monkeypatch.setenv(k,v)
    from urllib.parse import urlparse,parse_qs
    client.post('/api/register',json=REG)
    aid=parse_qs(urlparse(client.post('/api/billing/checkout',json={'start_now':True,'plan':'winq'}).json()['url']).query)['client_reference_id'][0]
    pay=lambda:client.post('/stripe/webhook',content=(ev:=json.dumps({'type':'checkout.session.completed','data':{'object':{'mode':'subscription','client_reference_id':aid,'customer':'cus_pl'}}})),headers=_signed(ev,'whsec_p'))
    client.post('/api/billing/checkout',json={'start_now':True,'plan':'winq'});pay()
    import control.app as capp
    capp.q("UPDATE accounts SET plan_status='canceled' WHERE id=?",(int(aid),))
    client.post('/api/billing/checkout',json={'start_now':True,'plan':'casanova'});pay()
    assert ('PUT','/v1/services/srv-new/env-vars/PLAN',{'value':'casanova'}) in calls
