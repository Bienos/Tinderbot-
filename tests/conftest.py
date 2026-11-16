import pytest
from agent import storage as s,runtime as rt
# The deployed bots run this suite in their build (python -m pytest) with their own production settings in the environment.
# A test must never inherit those: one extra setting on a server (PUBLIC_ORIGIN for a custom domain, TRIAL_DAYS, a plan...)
# used to fail the whole build and block the deploy. Tests that need one of these set it themselves.
HOST_SETTINGS=('PUBLIC_ORIGIN','RENDER_EXTERNAL_URL','CONTROL_ORIGIN','OWNER_PANEL_URL','OWNER_EMAIL','OWNER_SERVICE_ID','SSO_SECRET',
               'TRIAL_DAYS','PLAN','PLAN_CONVERSATIONS','DATABASE_URL','WEEKLY_SUMMARY','BRAND_NAME','PLAN_PRICE','MAIL_FROM','MAIL_DOMAIN',
               'MAIL_REPLY_TO','SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD','TRUST_PROXY','CUSTOM_DOMAIN','FLY_PUBLIC_DOMAIN')
@pytest.fixture(autouse=True)
def isolate_from_host_settings(monkeypatch):
    for name in HOST_SETTINGS:monkeypatch.delenv(name,raising=False)

@pytest.fixture(autouse=True)
def automation_window_always_open(monkeypatch):
    # The sending window of Automatyzuj depends on the clock; tests of sending must not. Window tests set their own.
    monkeypatch.setenv('CAMPAIGN_WINDOW','always')

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
    from agent import tinder_traffic;tinder_traffic._OWNER_CHECKS.clear()  # in-memory owner-check cap must not leak between tests
    rt.init();return s
