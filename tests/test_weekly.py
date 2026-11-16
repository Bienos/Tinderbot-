"""Weekly summary e-mail and fleet check (control service). The customers' bots are simulated by an httpx MockTransport that
verifies the request signature with the bot's own check (agent.auth), so the two halves are proven to agree."""
import json,re,time
from datetime import datetime,timezone
import httpx,pytest
from fastapi.testclient import TestClient

ADMIN={'Authorization':'Bearer '+'a'*32}
REG={'email':'Ola@Example.com','password':'bardzo-tajne-haslo','name':'Ola','mode':'drafts','adult':True,'terms':True}
SECRET_FOR={}
BOX=[]   # mail captured by the fake SMTP server (sign-up mails are dropped, only the summaries matter here)
SUN_21=datetime(2026,11,15,20,0,tzinfo=timezone.utc).timestamp()      # Sunday 21:00 Warsaw: the slot (20:00) has just passed

def summary(**over):
    base={'version':1,'generated_at':'2026-11-16T09:00:00+00:00','period_days':7,
          'this':{'matches':12,'messages_you':40,'messages_them':31,'asked':25,'answered':18,'reply_rate':72,'meetings':1,'contacts':2,'sent_by_agent':64},
          'prev':{'matches':9,'messages_you':30,'messages_them':20,'asked':20,'answered':12,'reply_rate':60,'meetings':0,'contacts':1,'sent_by_agent':40},
          'now':{'needs_reply':3,'invite_window':2,'conversations':14,'matches_total':30},
          'health':{'status':'ok','issues':[],'tinder':{'configured':True,'connections':1,'connected':True,'last_sync_age_min':4},
                    'agent':{'paused':False,'mode':'supervised','worker_running':True}}}
    for k,v in over.items():base[k]=v
    return base

@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('CONTROL_DB_PATH',str(tmp_path/'c.db'));monkeypatch.setenv('ADMIN_TOKEN','a'*32)
    monkeypatch.setenv('PUBLIC_ORIGIN','https://winq.example')
    for k in ('STRIPE_SECRET_KEY','STRIPE_PRICE_ID','STRIPE_WEBHOOK_SECRET','STRIPE_PAYMENT_LINK'):monkeypatch.delenv(k,raising=False)   # no billing: everyone has access
    import control.app as c
    from control import weekly,mailer
    c._HITS.clear();SECRET_FOR.clear();mailer.SENT.clear()
    return c

class Bots:
    """What the customers' bots answer. A callable per host, or a status code."""
    def __init__(self):self.answers={};self.calls=[]
    def __call__(self,request):
        from agent import auth
        host=request.url.host;self.calls.append(host)
        secret=SECRET_FOR[host]
        import os;os.environ['SSO_SECRET']=secret
        ok=auth.verify_control_request(request.headers.get('x-winq-ts',''),request.headers.get('x-winq-sig',''),f'https://{host}','summary')
        if not ok:return httpx.Response(401,json={'detail':'Unauthorized'})
        answer=self.answers.get(host,summary())
        if isinstance(answer,httpx.Response):return answer
        return answer(request) if callable(answer) else httpx.Response(200,json=answer)

@pytest.fixture
def bots(monkeypatch):
    from control import weekly
    b=Bots();monkeypatch.setattr(weekly,'TRANSPORT',httpx.MockTransport(b));return b

@pytest.fixture
def smtp(monkeypatch):
    """A fake mail server: captures what would have been sent."""
    import smtplib
    sent=BOX;sent.clear()
    class FakeSMTP:
        def __init__(self,*a,**k):pass
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def starttls(self,**k):pass
        def login(self,*a):pass
        def send_message(self,msg):sent.append(msg)
    monkeypatch.setattr(smtplib,'SMTP',FakeSMTP)
    monkeypatch.setenv('SMTP_HOST','smtp.example');monkeypatch.setenv('SMTP_USERNAME','u');monkeypatch.setenv('SMTP_PASSWORD','p');monkeypatch.setenv('MAIL_FROM','kontakt@winq.example')
    return sent

def tc(c):
    return TestClient(c.app,base_url='https://winq.example',headers={'Origin':'https://winq.example'})   # https: the session cookie is Secure; the sign-up and account calls check the origin

def account(c,email='ola@example.com',host='bot1.example',age_days=10,comped=True):
    """A registered account bound to a bot at https://<host>."""
    client=tc(c);client.post('/api/register',json={**REG,'email':email})
    r=client.post('/admin/accounts/activate',headers=ADMIN,json={'email':email,'instance_url':f'https://{host}','comped':comped}).json()
    SECRET_FOR[host]=r['sso_secret']
    c.q('UPDATE accounts SET created=? WHERE email=?',(time.time()-age_days*86400,email))
    BOX.clear()
    return client

def run(c,now=SUN_21,**kw):
    return c.run_weekly(now,**kw)

# ---- the weekly slot
def test_slot_is_sunday_8pm_warsaw():
    from control.weekly import slot_start
    sunday8pm=datetime(2026,11,15,19,0,tzinfo=timezone.utc).timestamp()   # 20:00 Warsaw (UTC+1)
    assert slot_start(sunday8pm)==sunday8pm and slot_start(sunday8pm+6*86400+3*3600)==sunday8pm   # the whole week points at the same slot
    assert slot_start(sunday8pm-60)==sunday8pm-7*86400                                     # one minute earlier: last week's slot
    summer=datetime(2026,7,12,18,0,tzinfo=timezone.utc).timestamp()          # 20:00 Warsaw in summer (UTC+2)
    assert slot_start(summer)==summer and slot_start(summer-60)==summer-7*86400

# ---- the message
def test_message_has_status_numbers_changes_and_one_link_into_statistics():
    from control import mailer
    spec=mailer.weekly_spec(summary(),'https://winq.example','https://winq.example/wypisz-sie?t=abc')
    text,html=mailer.render(spec)
    assert spec['subject']=='Twój tydzień w Winq: 12 nowych dopasowań'
    assert 'Nowe dopasowania: 12 (+3 wobec poprzedniego tygodnia)' in text and 'Odpowiedzi na Twoje wiadomości: 72% (+12 pp' in text
    assert '3 osoby czekają na Twoją odpowiedź' in text and '2 rozmowy są w oknie na zaproszenie' in text and '64 wiadomości' in text
    assert 'Wszystko działa' in text and 'Zobacz pełne statystyki: https://winq.example/konto/panel?view=stats' in text
    assert 'wypisz-sie?t=abc' in text and 'wypisz-sie?t=abc' in html and '>12<' in html and 'Zobacz pełne statystyki' in html
    assert spec['headers']['List-Unsubscribe']=='<https://winq.example/wypisz-sie?t=abc>' and spec['headers']['List-Unsubscribe-Post']=='List-Unsubscribe=One-Click'

@pytest.mark.parametrize('issues,expect',[
    (['tinder_error:session_expired_or_account_changed'],'Sesja Tindera wygasła'),
    (['sync_stale'],'od dawna nie zsynchronizował'),
    (['agent_paused'],'Agent jest wstrzymany'),
    (['tinder_error:something_new'],'Połączenie z Tinderem wymaga uwagi')])
def test_problems_are_named_in_the_status(issues,expect):
    from control import mailer
    s=summary();s['health']={**s['health'],'status':'problem','issues':issues}
    spec=mailer.weekly_spec(s,'https://winq.example','https://winq.example/wypisz-sie?t=x')
    assert spec['callout'][0]=='warn' and expect in spec['callout'][1] and spec['button'][0]=='Otwórz panel'
    from control import mailer as m;text,html=m.render(spec);assert text.index(expect)<text.index('Nowe dopasowania')   # a problem comes before the numbers

def test_not_connected_customer_gets_a_nudge_instead_of_empty_numbers():
    from control import mailer
    s=summary();s['health']={**s['health'],'status':'problem','issues':['tinder_not_connected']}
    spec=mailer.weekly_spec(s,'https://winq.example','https://winq.example/wypisz-sie?t=x')
    assert 'czeka na połączenie z Tinderem' in spec['subject'] and 'stats' not in spec

def test_quiet_week_and_small_sample_read_honestly():
    from control import mailer
    s=summary(this={**summary()['this'],'matches':0,'reply_rate':None,'meetings':0,'contacts':0,'sent_by_agent':0},now={'needs_reply':0,'invite_window':0,'conversations':0,'matches_total':0})
    spec=mailer.weekly_spec(s,'https://winq.example','https://winq.example/wypisz-sie?t=x')
    assert spec['subject']=='Twój tydzień w Winq: podsumowanie' and spec['stats'][2]['value']=='—' and spec['stats'][2]['note']=='za mało danych'
    assert 'Spokojny tydzień' in spec['paragraphs'][1]

# ---- the weekly pass
def test_sends_once_per_week_to_each_customer_with_a_signed_request(env,bots,smtp):
    c=env;account(c);account(c,'jan@example.com','bot2.example')
    res=run(c);assert sorted(r['result'] for r in res)==['sent','sent']
    assert len(smtp)==2 and {m['To'] for m in smtp}=={'ola@example.com','jan@example.com'}
    msg=smtp[0];assert msg['List-Unsubscribe'].startswith('<https://winq.example/wypisz-sie?t=') and 'Twój tydzień' in msg['Subject']
    body=msg.get_body(preferencelist=('plain',)).get_content();assert 'konto/panel?view=stats' in body
    assert sorted(bots.calls)==['bot1.example','bot2.example']
    assert [r['result'] for r in run(c,SUN_21+3600)]==['skipped: already sent this week']*2 and len(smtp)==2    # an hour later: nothing again
    assert all(r['result']=='sent' for r in run(c,SUN_21+7*86400)) and len(smtp)==4                                # next Sunday: again

def test_unreachable_bot_is_retried_and_only_marked_after_a_real_send(env,bots,smtp):
    c=env;account(c)
    bots.answers['bot1.example']=httpx.Response(503)
    res=run(c);assert res[0]['result'].startswith('failed') and not smtp
    row=c.q('SELECT weekly_sent_at,weekly_claim,weekly_note FROM accounts',fetch=True)[0]
    assert row['weekly_sent_at'] is None and row['weekly_claim'] is None and row['weekly_note'].startswith('failed')
    bots.answers.pop('bot1.example')                                                  # the bot is back
    assert run(c,SUN_21+1800)[0]['result']=='sent' and len(smtp)==1

def test_old_bot_without_the_endpoint_does_not_break_the_pass(env,bots,smtp):
    c=env;account(c);account(c,'jan@example.com','bot2.example')
    bots.answers['bot1.example']=httpx.Response(404)
    r={x['email']:x['result'] for x in run(c)}
    assert r['ola@example.com'].startswith('failed') and r['jan@example.com']=='sent'

def test_rules_who_gets_it(env,bots,smtp):
    c=env;account(c,'new@example.com','bot1.example',age_days=1)
    assert run(c)[0]['result']=='skipped: account too new'
    c.q('UPDATE accounts SET created=? WHERE email=?',(time.time()-9*86400,'new@example.com'))
    assert run(c,SUN_21+48*3600)[0]['result']=='skipped: outside the weekly window'        # Tuesday 21:00: this week is over
    assert run(c,SUN_21+46*3600)[0]['result']=='sent'                                         # Tuesday 19:00: still catching up
    c.q('UPDATE accounts SET weekly_summary=0')
    assert run(c,SUN_21+7*86400)==[]                                                       # opted out: not even a candidate

def test_billing_gate_and_withdrawn_accounts_get_nothing(env,bots,smtp,monkeypatch):
    c=env;account(c,comped=False)
    monkeypatch.setenv('STRIPE_PAYMENT_LINK','https://buy.stripe.com/t');monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_x')   # billing on, plan_status none
    assert run(c)[0]['result']=='skipped: no access' and not smtp
    c.q("UPDATE accounts SET plan_status='active'");c.q('UPDATE accounts SET withdrawn_at=?',(time.time(),))
    assert run(c)==[]

def test_mail_not_configured_marks_nothing(env,bots,monkeypatch):
    c=env;account(c)
    for k in ('SMTP_HOST','SMTP_USERNAME','SMTP_PASSWORD'):monkeypatch.delenv(k,raising=False)
    assert run(c)[0]['result']=='skipped: mail is not configured'
    assert c.q('SELECT weekly_sent_at FROM accounts',fetch=True)[0]['weekly_sent_at'] is None and not bots.calls

def test_dry_run_and_force_and_single_account(env,bots,smtp):
    c=env;account(c);account(c,'jan@example.com','bot2.example')
    d=run(c,dry_run=True);assert all(r['result']=='dry run' and r['subject'].startswith('Twój tydzień') and r['health']=='ok' for r in d) and not smtp
    assert c.q('SELECT COUNT(*) n FROM accounts WHERE weekly_sent_at IS NOT NULL',fetch=True)[0]['n']==0
    assert [r['result'] for r in run(c,email='JAN@example.com')]==['sent'] and len(smtp)==1
    assert run(c,SUN_21+86400*4,force=True,email='jan@example.com')[0]['result']=='sent'       # force: any day, even if already sent

def test_two_processes_cannot_both_send(env,bots,smtp):
    c=env;account(c)
    c.q('UPDATE accounts SET weekly_claim=?',(SUN_21-5,))                          # another process claimed it five seconds ago
    assert run(c)[0]['result']=='skipped: another run has it' and not smtp
    assert run(c,SUN_21+700)[0]['result']=='sent'                                  # an abandoned claim (older than 10 minutes) is taken over

# ---- the customer's controls
def test_unsubscribe_link_one_click_and_account_toggle(env,bots,smtp):
    c=env;client=account(c);run(c)
    token=re.search(r'wypisz-sie\?t=([\w-]+)',smtp[0]['List-Unsubscribe']).group(1)
    page=client.get('/wypisz-sie?t='+token);assert page.status_code==200 and 'Tak, wypisz mnie' in page.text and 'noindex' in page.text
    assert 'nieprawidłowy' in client.get('/wypisz-sie?t=nope').text and client.post('/wypisz-sie?t=nope').status_code==404
    assert client.get('/api/me').json()['weekly_summary'] is True
    done=client.post('/wypisz-sie?t='+token,data={'List-Unsubscribe':'One-Click'});assert done.status_code==200 and 'wypisaliśmy' in done.text
    assert client.get('/api/me').json()['weekly_summary'] is False and run(c,SUN_21+7*86400)==[]
    assert client.post('/api/account/weekly',json={'enabled':True}).json()['weekly_summary'] is True
    assert client.get('/api/me').json()['weekly_summary'] is True

def test_email_link_goes_through_login_then_straight_to_the_statistics(env,bots,smtp):
    c=env;client=account(c);anon=tc(c)
    r=anon.get('/konto/panel?view=stats',follow_redirects=False);assert r.headers['location']=='/zaloguj?next=%2Fkonto%2Fpanel%3Fview%3Dstats'
    assert anon.get('/konto/panel',follow_redirects=False).headers['location']=='/zaloguj'
    assert 'view=stats' in open('control/static/account.js',encoding='utf-8').read()
    loc=client.get('/konto/panel?view=stats',follow_redirects=False).headers['location']
    assert loc.startswith('https://bot1.example/auth/sso?t=') and loc.endswith('&next=stats')
    plain=client.get('/konto/panel',follow_redirects=False).headers['location'];assert plain.startswith('https://bot1.example/auth/sso?t=') and 'next=' not in plain   # without the view: unchanged

# ---- operator tools
def test_admin_endpoints_need_the_admin_token(env):
    client=tc(env)
    assert client.post('/admin/weekly/run',json={}).status_code==401 and client.get('/admin/fleet').status_code==401

def test_admin_weekly_run_dry_then_real(env,bots,smtp):
    c=env;account(c);client=tc(c)
    d=client.post('/admin/weekly/run',headers=ADMIN,json={'dry_run':True,'force':True}).json()
    assert d['count']==1 and d['sent']==0 and d['items'][0]['result']=='dry run' and not smtp
    r=client.post('/admin/weekly/run',headers=ADMIN,json={'force':True}).json();assert r['sent']==1 and len(smtp)==1

def test_fleet_check_reports_every_instance_and_flags_the_broken_ones(env,bots):
    c=env;account(c);account(c,'jan@example.com','bot2.example');account(c,'eva@example.com','bot3.example')
    bad=summary();bad['health']={**bad['health'],'status':'problem','issues':['tinder_error:session_expired_or_account_changed'],'tinder':{**bad['health']['tinder'],'connected':False}}
    bots.answers['bot2.example']=bad;bots.answers['bot3.example']=httpx.Response(502)
    d=tc(c).get('/admin/fleet',headers=ADMIN).json()
    by={i['email']:i for i in d['items']}
    assert d['count']==3 and d['reachable']==2 and d['problems']==2
    assert by['ola@example.com']['status']=='ok' and by['ola@example.com']['tinder_connected'] and by['ola@example.com']['last_sync_age_min']==4
    assert by['jan@example.com']['status']=='problem' and not by['jan@example.com']['tinder_connected']
    assert by['eva@example.com']['reachable'] is False and 'HTTP 502' in by['eva@example.com']['error']
    assert 'sso_secret' not in json.dumps(d)

def test_admin_accounts_lists_weekly_state(env,bots,smtp):
    c=env;account(c);run(c)
    item=tc(c).get('/admin/accounts',headers=ADMIN).json()['items'][0]
    assert item['weekly_summary']==1 and item['weekly_sent_at']==SUN_21 and item['weekly_note']=='sent'

def test_verified_results_are_left_out_for_plans_without_advanced_statistics():
    from control import mailer
    def labels(plan):
        s=summary();s['plan']=plan
        return [x['label'] for x in mailer.weekly_spec(s,'https://winq.example','https://winq.example/wypisz-sie?t=x')['stats']]
    basic=['Nowe dopasowania','Wiadomości od nich','Odpowiedzi na Twoje wiadomości']
    assert labels({'name':'flirt','advanced_stats':False})==basic
    assert labels({'name':'casanova','advanced_stats':True})==basic+['Spotkania i kontakty']
    assert labels(None)==basic+['Spotkania i kontakty']             # an older bot or the owner's own: nothing is limited
