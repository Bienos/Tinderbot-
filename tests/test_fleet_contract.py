"""What every newly created customer bot must have so that statistics, the weekly e-mail and the fleet check work.
The test starts a bot with exactly the settings provisioning generates and talks to it the way the control service does."""
import json,time
import httpx,pytest
from fastapi.testclient import TestClient

REQUIRED={'SSO_SECRET','CONTROL_ORIGIN','WORKER_ENABLED','TINDER_ENABLED','DASHBOARD_TOKEN','TOKEN_ENCRYPTION_KEY','AGENT_DB_PATH','SEED_SIMULATOR','TINDER_REQUESTS_PER_MINUTE','TINDER_REQUESTS_PER_HOUR'}

def test_every_new_instance_gets_the_settings_the_weekly_summary_depends_on(monkeypatch):
    from control import provision
    monkeypatch.setenv('PUBLIC_ORIGIN','https://winq.example')
    env=provision.instance_env('k'*43,{'PLAN':'flirt'})
    assert REQUIRED<=set(env) and len(env['SSO_SECRET'])>=32 and env['CONTROL_ORIGIN']=='https://winq.example'
    assert env['WORKER_ENABLED']=='true' and env['TINDER_ENABLED']=='true' and env['SEED_SIMULATOR']=='false' and env['PLAN']=='flirt'
    monkeypatch.setenv('RENDER_OWNER_ID','tea-x')
    body={e['key']:e['value'] for e in provision.service_body('n','k'*43)['envVars']}      # the Render path builds on the same settings
    assert REQUIRED<=set(body) and body['SSO_SECRET']=='k'*43

def test_a_bot_started_with_those_settings_answers_the_control_service_and_the_sign_in_link(store,monkeypatch):
    from control import provision,weekly,app as capp
    secret='k'*43;origin='https://bot-abc.winq.example'
    monkeypatch.setenv('PUBLIC_ORIGIN','https://winq.example')                          # the control service's own address
    env=provision.instance_env(secret,{'PLAN':'flirt'});env.update({'PUBLIC_ORIGIN':origin,'PORT':'8080'})   # what Fly adds on top
    for k,v in env.items():
        if k not in ('AGENT_DB_PATH','SEED_SIMULATOR','DATING_AGENT_SOURCE'):monkeypatch.setenv(k,v)
    monkeypatch.setenv('DATING_AGENT_SOURCE','fixture')
    from app import app
    with TestClient(app,base_url=origin) as bot:
        time.sleep(0.3)
        def forward(request):                                                            # the control service's HTTP client, routed into the bot
            r=bot.get(request.url.path,params=dict(request.url.params),headers={k:v for k,v in request.headers.items() if k.startswith('x-winq')})
            return httpx.Response(r.status_code,content=r.content,headers={'content-type':r.headers['content-type']})
        monkeypatch.setattr(weekly,'TRANSPORT',httpx.MockTransport(forward))
        doc=weekly.fetch(secret,origin)                                                  # signed by the control service, accepted by the bot
        assert doc['version']==1 and doc['health']['agent']['worker_running'] is True and doc['health']['agent']['paused'] is False
        assert 'tinder_not_connected' in doc['health']['issues']                         # a fresh bot is healthy but waits for the customer's token
        with pytest.raises(RuntimeError):weekly.fetch('x'*43,origin)                     # a bot never answers with another customer's secret
        acc={'email':'ola@example.com','sso_secret':secret,'instance_url':origin}
        link=capp.sso_token(acc)
        ok=bot.get('/auth/sso',params={'t':link,'next':'stats'});assert ok.status_code==200 and '#stats' in ok.text and 'agent_session' in ok.cookies
        assert bot.get('/api/state').status_code==200                                    # and the session works: the dashboard can load the data the stats tab reads
        mail=capp.mailer.weekly_spec(doc,'https://winq.example','https://winq.example/wypisz-sie?t=x')   # the real document produces a real message
        assert mail['callout'][0]=='warn' and 'czeka na połączenie' in mail['subject']
