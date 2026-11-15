import pytest
from agent import storage as s,runtime as rt
@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DB_PATH',tmp_path/'test.db')
    monkeypatch.setenv('DATING_AGENT_SOURCE','fixture')
    monkeypatch.setenv('WORKER_ENABLED','false')
    monkeypatch.setenv('PUBLIC_ORIGIN','http://testserver')
    monkeypatch.setenv('DASHBOARD_TOKEN','test-dashboard-token-at-least-32-chars')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setenv('TINDER_ENABLED','false')
    monkeypatch.delenv('TINDER_AUTH_TOKEN',raising=False)
    monkeypatch.delenv('TINDER_OWNER_ID',raising=False)
    rt.init();return s
