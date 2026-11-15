"""Hosted-origin security and clean persistent single-worker startup. No live account calls."""
import json
import pytest
from fastapi.testclient import TestClient
from agent import storage as s,runtime as rt
from agent.http_security import public_origin

@pytest.mark.parametrize('external',['https://tinderbot-example.onrender.com','https://tinderbot-example.onrender.com/'])
def test_render_https_origin_clean_worker_and_persistent_settings(tmp_path,monkeypatch,external):
    from app import app
    monkeypatch.setattr(s,'DB_PATH',tmp_path/'disk'/'agent.db')
    monkeypatch.delenv('PUBLIC_ORIGIN',raising=False);monkeypatch.setenv('RENDER_EXTERNAL_URL',external)
    monkeypatch.setenv('DASHBOARD_TOKEN','cloud-test-token-at-least-thirty-two-characters')
    monkeypatch.setenv('WORKER_ENABLED','true');monkeypatch.setenv('WORKER_INTERVAL','0.1')
    monkeypatch.setenv('SEED_SIMULATOR','false');monkeypatch.setenv('DATING_AGENT_SOURCE','fixture')
    monkeypatch.setenv('TINDER_ENABLED','false');monkeypatch.delenv('TINDER_AUTH_TOKEN',raising=False)
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    url='https://tinderbot-example.onrender.com'
    assert public_origin()==url
    with TestClient(app,base_url=url) as c:
        assert c.get('/health').status_code==200
        assert c.get('/').status_code==401
        r=c.post('/auth/login',json={'token':'cloud-test-token-at-least-thirty-two-characters'})
        assert r.status_code==200 and 'Secure' in r.headers['set-cookie']
        data=c.get('/api/state').json();assert data['threads']==[] and data['worker']['running']
        cfg=data['settings'];cfg['language']='en'
        assert c.put('/api/settings',json=cfg,headers={'Origin':url}).status_code==200
        assert c.get('/api/state',headers={'Host':'attacker.example'}).status_code==400
    with TestClient(app,base_url=url) as c:
        c.post('/auth/login',json={'token':'cloud-test-token-at-least-thirty-two-characters'})
        assert c.get('/api/state').json()['settings']['language']=='en'

def test_explicit_origin_overrides_render_default_and_invalid_origin_fails_closed(monkeypatch):
    monkeypatch.setenv('RENDER_EXTERNAL_URL','https://generated.onrender.com')
    monkeypatch.setenv('PUBLIC_ORIGIN','https://private.example')
    assert public_origin()=='https://private.example'
    monkeypatch.setenv('PUBLIC_ORIGIN','https://user:password@private.example/path')
    with pytest.raises(RuntimeError):public_origin()
