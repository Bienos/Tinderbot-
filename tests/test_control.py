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
