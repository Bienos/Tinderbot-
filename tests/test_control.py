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
    me=client.get('/api/me').json();assert me=={'email':'ola@example.com','name':'Ola','status':'pending','panel_ready':False}
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
