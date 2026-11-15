import pytest
from agent import storage as s,runtime as rt
@pytest.fixture(autouse=True)
def disable_operator_startup_check(monkeypatch):
    # A production troubleshooting flag must not add real network calls to tests.
    monkeypatch.setenv('TINDER_STARTUP_CHECK','false')

@pytest.fixture
def store(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DB_PATH',tmp_path/'test.db')
    monkeypatch.setenv('DATING_AGENT_SOURCE','fixture')
    monkeypatch.setenv('SEED_SIMULATOR','true')
    monkeypatch.setenv('COOKIE_SECURE','false')
    monkeypatch.setenv('WORKER_ENABLED','false')
    monkeypatch.setenv('PUBLIC_ORIGIN','http://testserver')
    monkeypatch.setenv('DASHBOARD_TOKEN','test-dashboard-token-at-least-32-chars')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    monkeypatch.delenv('LLM_PROVIDER',raising=False)
    monkeypatch.delenv('OPENAI_MODEL',raising=False)
    monkeypatch.delenv('ANTHROPIC_MODEL',raising=False)
    monkeypatch.setenv('TINDER_ENABLED','false')
    monkeypatch.delenv('TINDER_AUTH_TOKEN',raising=False)
    monkeypatch.delenv('TINDER_OWNER_ID',raising=False)
    rt.init();return s
