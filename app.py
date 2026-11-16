"""Single-owner authorized conversation agent. Run one ASGI worker per database."""
import asyncio,contextlib,html,json,os,secrets,time
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse,HTMLResponse
from pydantic import BaseModel,Field,ConfigDict
from agent import storage as s,runtime as rt,service,campaigns,tinder as tinder_integration
from agent.auth import token,same_secret,create_session,session_valid,revoke_session
from agent.http_security import SecurityBoundary,internal_request,public_origin
from agent.dispatch import DispatchDenied
from agent.llm import configured as model_configured
from agent.diagnostics import report_failure,tinder_startup_check
from agent.adapters import StaleAction,sim_send,telegram_update
from agent.triage import project
BASE=Path(__file__).resolve().parent
# Public, pre-login pages share the landing page's look (control/static/landing.css): palette, type and the iskra wordmark.
WORDMARK=(BASE/'static/wordmark.svg').read_text(encoding='utf-8').strip().replace('<svg ','<svg class="wordmark" aria-hidden="true" focusable="false" ',1)
PAGE_CSS=(':root{--pink:#fd267a;--ink:#2a0f22;--text:#57404f;--muted:#8a7482;--line:#f0e3e9;--grad:linear-gradient(120deg,#fd267a 0%,#ff6036 100%);'
 'font-family:"Onest",ui-sans-serif,system-ui,sans-serif;color-scheme:light}*{box-sizing:border-box}'
 'body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px 16px;color:var(--text);font-size:16px;line-height:1.55;'
 'background:radial-gradient(1200px 700px at 85% -10%,#ffe1ea 0%,transparent 60%),radial-gradient(900px 600px at -10% 30%,#fff0e6 0%,transparent 55%),#fff6f8}'
 'main{width:min(440px,100%);background:#fff;border-radius:28px;padding:36px 32px;box-shadow:0 24px 60px -28px rgba(42,15,34,.35)}'
 '.brand{line-height:0;margin-bottom:28px}.brand .wordmark{height:28px;width:auto;display:block}'
 'h1{font-family:"Unbounded","Onest",sans-serif;font-weight:650;font-size:24px;line-height:1.15;letter-spacing:-.03em;color:var(--ink);margin:0 0 10px}p{margin:0 0 22px}'
 '.btn{display:block;width:100%;text-align:center;border:0;cursor:pointer;background:var(--grad);color:#fff;text-decoration:none;font:inherit;font-weight:700;padding:14px 22px;border-radius:999px;box-shadow:0 10px 30px -10px rgba(253,38,122,.65)}'
 'input{display:block;width:100%;font:inherit;padding:12px 16px;border:2px solid var(--line);border-radius:14px;background:#fff6f8;color:var(--ink);margin:0 0 12px}input:focus{outline:0;border-color:var(--pink)}'
 ':focus-visible{outline:3px solid #ff6036;outline-offset:3px}details{margin-top:24px;border-top:1px solid var(--line);padding-top:16px}'
 'summary{cursor:pointer;color:var(--muted);font-size:14px;font-weight:600}details[open] summary{margin-bottom:14px}'
 'small{display:block;color:var(--muted);font-size:13px;margin-top:14px}#error{color:#c8104f;font-size:14px;margin:10px 0 0}#error:empty{display:none}'
 '@media(max-width:420px){main{padding:28px 22px}}')

def control_origin():
    """The Winq account site this instance belongs to (CONTROL_ORIGIN), or '' when it runs on its own."""
    value=os.getenv('CONTROL_ORIGIN','').strip().rstrip('/')
    return value if value.startswith(('https://','http://')) else ''

def brand_page(title,body,status=200,head=''):
    return HTMLResponse('<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta name="theme-color" content="#fff6f8"><link rel="icon" type="image/svg+xml" href="/static/icon.svg"><link rel="stylesheet" href="/static/fonts/fonts.css">{head}'
        f'<title>{html.escape(title)} · Winq</title><style>{PAGE_CSS}</style></head><body><main><div class="brand" role="img" aria-label="Winq">{WORDMARK}</div>{body}</main></body></html>',status)

def login_page():
    form=('<form><input type="password" autocomplete="current-password" required aria-label="Token dostępu" placeholder="Token dostępu">'
          '<button class="btn" type="submit">Zaloguj się</button><p id="error" role="alert"></p></form><script src="/static/login.js" defer></script>')
    account=control_origin()
    if account:
        body=(f'<h1>Zaloguj się do panelu</h1><p>Panel otwierasz ze swojego konta Winq. Zalogujemy Cię automatycznie.</p>'
              f'<a class="btn" href="{html.escape(account)}/konto/panel">Zaloguj się przez konto Winq</a>'
              f'<details><summary>Mam token dostępu</summary>{form}</details>')
    else:
        body=(f'<h1>Zaloguj się do panelu</h1><p>Wpisz token dostępu do panelu.</p>{form}'
              '<small>Lokalny token jest w pliku runtime/dashboard-token. Na serwerze ustaw DASHBOARD_TOKEN.</small>')
    return brand_page('Logowanie',body,401)
# Only these files are served from static/. The sign-in page needs its script, icon and fonts before login.
STATIC_FILES={'dashboard.js':'text/javascript','mock.js':'text/javascript','login.js':'text/javascript','icon.svg':'image/svg+xml','fonts/fonts.css':'text/css',
    **{f'fonts/{face}-{subset}-wght-normal.woff2':'font/woff2' for face in ('onest','unbounded') for subset in ('latin','latin-ext')}}
PUBLIC_STATIC=frozenset('/static/'+name for name in STATIC_FILES if name in ('login.js','icon.svg') or name.startswith('fonts/'))
LEASE_WAIT_SECONDS=75   # longer than LEASE_TTL, so a stale lease can never crash-loop the start
LEASE_TTL=60
LEASE_HEARTBEAT=15


def lease_owner():
    import socket
    return f'{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(8)}'


def _pid_alive(pid):
    try:os.kill(pid,0)
    except PermissionError:return True
    except OSError:return False
    return True


def lease_blocks(prior,owner):
    """Is another LIVE worker of this container holding the lease? Anything else is stale and is taken over at once:
    a previous container (the data disk moved to us, only one container can mount it) or an earlier process of this
    container that is gone (killed while shutting down, so it never released the lease; it can even have had our pid)."""
    if not prior or prior['expires']<=time.time():return False
    host,_,rest=prior['owner'].partition(':');mine,_,mine_rest=owner.partition(':')
    if host!=mine:return False
    try:other=int(rest.split(':',1)[0]);me=int(mine_rest.split(':',1)[0])
    except ValueError:return True
    if other==me:return False
    return _pid_alive(other)


@asynccontextmanager
async def lifespan(app):
    public_origin();rt.init();token()
    # A process lease prevents independent workers reserving simultaneous browser sends.
    owner=lease_owner()
    for attempt in range(LEASE_WAIT_SECONDS):
        with s.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute("SELECT * FROM leases WHERE name='coordinator'").fetchone()
            if not lease_blocks(prior,owner):
                db.execute('INSERT OR REPLACE INTO leases VALUES(?,?,?)',('coordinator',owner,time.time()+LEASE_TTL));break
        await asyncio.sleep(1)
    else:raise RuntimeError('Another coordinator owns this database; use one ASGI worker')
    rt.recover()
    import signal
    previous=signal.getsignal(signal.SIGTERM)
    def release_on_term(signum,frame):
        # A slow graceful shutdown (open connections) can end in a hard kill; free the lease and stop new work first,
        # so the replacement process starts at once instead of waiting for a lease that nobody will release.
        service.SHUTTING_DOWN=True
        try:
            with s.connect() as db:db.execute("DELETE FROM leases WHERE name='coordinator' AND owner=?",(owner,))
        except Exception:pass
        if callable(previous):previous(signum,frame)
    with contextlib.suppress(ValueError,OSError):signal.signal(signal.SIGTERM,release_on_term)
    async def heartbeat():
        while True:
            with s.connect() as db:db.execute("UPDATE leases SET expires=? WHERE name='coordinator' AND owner=?",(time.time()+LEASE_TTL,owner))
            await asyncio.sleep(LEASE_HEARTBEAT)
    hb=asyncio.create_task(heartbeat())
    task=asyncio.create_task(service.worker()) if os.getenv('WORKER_ENABLED','true')=='true' else None
    preflight=asyncio.create_task(tinder_startup_check()) if os.getenv('TINDER_STARTUP_CHECK','false')=='true' else None
    try:yield
    finally:
        for t in (task,hb,preflight):
            if t:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):await t
        with s.connect() as db:db.execute("DELETE FROM leases WHERE name='coordinator' AND owner=?",(owner,))
app=FastAPI(title='Authorized Conversation Agent',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
LOGIN_FAILURES={}
LOGIN_ATTEMPTS=[]

@app.middleware('http')
async def auth(request,call_next):
    origin=request.headers.get('origin')
    allowed=public_origin()
    if request.method not in ('GET','HEAD','OPTIONS') and origin and origin!=allowed and not (origin=='http://127.0.0.1:8765' and internal_request(request.scope)):return JSONResponse({'detail':'Cross-origin request blocked'},403)
    path=request.url.path
    if path not in ('/health','/auth/login','/auth/sso','/webhooks/telegram','/internal/summary') and path not in PUBLIC_STATIC:
        auth=request.headers.get('authorization','')
        authenticated=same_secret(auth[7:],token()) if auth.startswith('Bearer ') else session_valid(request.cookies.get('agent_session',''))
        if not authenticated:
            return login_page() if path=='/' else JSONResponse({'detail':'Authentication required'},401)
        # Cookie-authenticated mutations require an origin or non-simple custom header.
        if request.method not in ('GET','HEAD') and not auth and not origin and request.headers.get('x-agent-request')!='dashboard':
            return JSONResponse({'detail':'CSRF protection'},403)
    try:response=await call_next(request)
    except Exception as exc:
        route=request.scope.get('route')
        reference=report_failure(exc,getattr(route,'path','http_request'))
        return JSONResponse({'detail':'Unexpected application error. Reference: '+reference,'error_id':reference},500)
    return response

class Login(BaseModel):token:str=Field(max_length=256)
@app.post('/auth/login')
def login(body:Login,request:Request):
    host=request.client.host;now=time.time()
    LOGIN_ATTEMPTS[:]=[t for t in LOGIN_ATTEMPTS if now-t<60]
    if len(LOGIN_ATTEMPTS)>=100:raise HTTPException(429,'Try again later')
    LOGIN_ATTEMPTS.append(now)
    for key in list(LOGIN_FAILURES):
        LOGIN_FAILURES[key]=[t for t in LOGIN_FAILURES[key] if now-t<60]
        if not LOGIN_FAILURES[key]:LOGIN_FAILURES.pop(key,None)
    if host not in LOGIN_FAILURES and len(LOGIN_FAILURES)>=512:raise HTTPException(429,'Try again later')
    failures=[t for t in LOGIN_FAILURES.get(host,[]) if now-t<60]
    if len(failures)>=10:raise HTTPException(429,'Try again later')
    if not same_secret(body.token,token()):
        LOGIN_FAILURES[host]=failures+[now];raise HTTPException(401,'Sign in failed')
    LOGIN_FAILURES.pop(host,None)
    r=JSONResponse({'ok':True});r.set_cookie('agent_session',create_session(),httponly=True,samesite='strict',secure=public_origin().startswith('https://') or os.getenv('COOKIE_SECURE','false')=='true',max_age=3600*12)
    return r
@app.get('/auth/sso')
def sso(t:str='',next:str='',request:Request=None):
    """Single sign-on from the Winq account page: a 60-second, single-use token HMAC-signed with SSO_SECRET."""
    from agent.auth import verify_sso
    if not verify_sso(t,public_origin()):
        account=control_origin()
        again=f'<a class="btn" href="{html.escape(account)}/konto/panel">Otwórz panel jeszcze raz</a>' if account else ''
        return brand_page('Link wygasł','<h1>Link logowania wygasł</h1><p>Ten link działa raz i tylko przez minutę. Wróć do konta i otwórz panel jeszcze raz.</p>'+again,401)
    # A same-site meta refresh (not a 30x) so the SameSite=Strict session cookie is sent on the next request.
    target='/#stats' if next=='stats' else '/'  # only a known view name is accepted, never a free address
    r=brand_page('Logowanie','<h1>Logowanie…</h1><p>Otwieramy Twój panel.</p>',head=f'<meta http-equiv="refresh" content="0;url={target}">')
    r.set_cookie('agent_session',create_session(),httponly=True,samesite='strict',secure=public_origin().startswith('https://') or os.getenv('COOKIE_SECURE','false')=='true',max_age=3600*12)
    return r

@app.post('/auth/logout')
def logout(request:Request):
    revoke_session(request.cookies.get('agent_session',''))
    r=JSONResponse({'ok':True});r.delete_cookie('agent_session');return r
@app.get('/health')
def health():return {'status':'ok'}
_SUMMARY_CACHE={'at':0.0,'key':None,'value':None}
@app.get('/internal/summary')
def internal_summary(request:Request,days:int=7):
    """Counts for the weekly e-mail and the fleet check. Only the control service can call it (signed with SSO_SECRET);
    the answer holds numbers and health codes, never names or message text."""
    from agent.auth import verify_control_request
    if not verify_control_request(request.headers.get('x-winq-ts',''),request.headers.get('x-winq-sig',''),public_origin(),'summary'):
        raise HTTPException(401,'Unauthorized')
    days=max(1,min(30,days));c=_SUMMARY_CACHE;key=(days,str(s.DB_PATH))  # a few seconds of reuse protects the bot from repeated polling
    if c['value'] is None or c['key']!=key or time.time()-c['at']>30:
        from agent import summary
        c.update(at=time.time(),key=key,value=summary.weekly(days=days))
    return c['value']
@app.get('/')
def home():return FileResponse(BASE/'static/dashboard.html')
@app.get('/mock')
def mock():return FileResponse(BASE/'static/mock.html')
@app.get('/api/mock/source')
def source():
    threads=[t for t in s.threads() if t['platform']=='simulator' and t['source_visibility']=='available']
    receipts={r['message_id']:r['action_id'] for r in s.rows('SELECT * FROM sim_receipts')}
    return {'threads':threads,'messages':{t['id']:[{**m,'action_id':receipts.get(m['id'],'')} for m in s.source_for_thread(t['id'])] for t in threads}}
class Send(BaseModel):
    thread_id:str=Field(pattern=r'^t[0-9]+$')
    body:str=Field(min_length=1,max_length=450)
    action_id:str=Field(min_length=1,max_length=120)
    anchor:str=Field(max_length=200)
@app.post('/api/mock/send')
def send(body:Send):
    try:return {'ok':True,'message_id':sim_send(body.thread_id,body.body,body.action_id,body.anchor)}
    except StaleAction:raise HTTPException(409,'Stale message')
    except PermissionError:raise HTTPException(403,'Permission revoked')
@app.post('/api/sync')
async def sync():
    if service.TICK.locked() or service.SYNC.locked():raise HTTPException(409,'Coordinator busy')
    before=len(s.notifications());drafts=len(s.all_drafts())
    try:await service.tick()
    except Exception:raise HTTPException(503,'Source synchronization failed; check browser or configuration')
    return {'new_verified_notifications':len(s.notifications())-before,'drafts_created':len(s.all_drafts())-drafts,'source':os.getenv('DATING_AGENT_SOURCE','browser')}

def build_stats(threads,hist,outcomes):
    from collections import Counter
    from datetime import datetime,timedelta,timezone
    by_state=Counter(t['state'] for t in threads)
    mine=sum(1 for t in threads for m in hist[t['id']] if m['sender']=='you');theirs=sum(1 for t in threads for m in hist[t['id']] if m['sender']!='you')
    wrote=replied=both=0
    for t in threads:
        seq=[m['sender'] for m in hist[t['id']]]
        if 'you' in seq and any(x!='you' for x in seq):both+=1
        if 'you' in seq:
            wrote+=1
            if any(x!='you' for x in seq[seq.index('you'):]):replied+=1
    today=datetime.now(timezone.utc).date();days=[(today-timedelta(days=i)).isoformat() for i in range(6,-1,-1)]
    per_day={d:{'you':0,'them':0} for d in days}
    for t in threads:
        for m in hist[t['id']]:
            d=str(m.get('created_at',''))[:10]
            if d in per_day:per_day[d]['you' if m['sender']=='you' else 'them']+=1
    now=time.time()
    try:
        req={'minute':s.rows('SELECT COUNT(*) n FROM tinder_requests WHERE ts>?',(now-60,))[0]['n'],'hour':s.rows('SELECT COUNT(*) n FROM tinder_requests WHERE ts>?',(now-3600,))[0]['n']}
    except Exception:req=None
    moves=[t.get('plan') or {} for t in threads]
    kinds_by=[{o['kind'] for o in outcomes.get(t['id'],[])} for t in threads]
    funnel={'matches':len(threads),'conversations':sum(1 for t in threads if t.get('message_count')),
            'invite_window':sum(1 for m in moves if m.get('move')=='invite'),
            'invited':sum(1 for m,k in zip(moves,kinds_by) if m.get('stage') in ('awaiting_answer','logistics','date_set','cooldown') or k&{'date_suggested','date_tentative','date_confirmed'}),
            'agreed':sum(1 for m,k in zip(moves,kinds_by) if m.get('stage') in ('logistics','date_set') or k&{'date_tentative','date_confirmed'}),
            'confirmed':sum(1 for k in kinds_by if 'date_confirmed' in k),'instagram':sum(1 for k in kinds_by if 'instagram_shared' in k)}
    return {'funnel':funnel,'with_photos':sum(1 for t in threads if (t.get('profile') or {}).get('photos')),'matches':len(threads),'by_state':dict(by_state),'messages_you':mine,'messages_them':theirs,
            'conversations_two_way':both,'we_wrote':wrote,'they_replied':replied,
            'drafts':{r['status']:r['n'] for r in s.rows('SELECT status,COUNT(*) n FROM drafts GROUP BY status')},
            'actions':s.rows('SELECT status,automatic,COUNT(*) n FROM actions GROUP BY status,automatic'),
            'outcomes':dict(Counter(o['kind'] for lst in outcomes.values() for o in lst)),
            'per_day':[{'day':d,**per_day[d]} for d in days],'tinder_requests':req}
@app.get('/api/state')
def state():
    drafts=s.all_drafts();notes=s.notifications();rows=s.threads();by_thread=s.messages_by_thread();hist={t['id']:by_thread.get(t['id'],[]) for t in rows}
    outcomes={r['thread_id']:json.loads(r['value']) for r in s.rows('SELECT * FROM outcome_state')}
    from agent import strategy
    cfg=rt.settings()
    ctx={'cfg':cfg,'hist':hist,'grants':{g['thread_id']:g for g in s.rows('SELECT * FROM grants')}}  # read once, not per thread
    profiles={}
    for r in s.rows('SELECT thread_id,value FROM tinder_threads'):
        try:profiles[r['thread_id']]=json.loads(r['value']).get('profile')
        except ValueError:pass
    threads=[]
    for t in rows:
        p=project(t,hist[t['id']],[d for d in drafts if d['thread_id']==t['id']],[])
        p['outcomes']=[o['kind'] for o in outcomes.get(t['id'],[])];p['automatic_sending']=rt.auto_allowed(t,ctx);p['profile']=profiles.get(t['id']);h=hist[t['id']];p['sort_at']=(h[-1]['created_at'] if h else None) or (p['profile'] or {}).get('last_activity') or (p['profile'] or {}).get('matched_at') or '';p['matched_at']=(p['profile'] or {}).get('matched_at');p['plan']=strategy.analyze(hist[t['id']],cfg,outcomes.get(t['id'],[]));threads.append(p)
    mem=rt.memory_by_thread()
    from agent import plans
    plan=plans.status(rows,hist)
    if plan:
        waiting=set(plan['queued'])
        for p_ in threads:p_['queued']=p_['id'] in waiting
        plan['queued']=len(waiting)
    return {'plan':plan,'campaign':campaigns.status(hist),'threads':threads,'messages':hist,'drafts':drafts,'notifications':notes,'llm_enabled':model_configured(),
            'worker':service.WORKER,'settings':rt.settings(),'grants':s.rows('SELECT * FROM grants'),
            'memory':{t['id']:mem.get(t['id'],[]) for t in rows},'outcome_details':outcomes,
            'activity':s.rows('SELECT * FROM activity ORDER BY id DESC LIMIT 100'),
            'actions':s.rows('SELECT * FROM actions ORDER BY updated DESC LIMIT 100'),
            'connections':s.rows('SELECT id,enabled,can_reply FROM connections'),
            'tinder':tinder_integration.public_status(),'account_url':os.getenv('CONTROL_ORIGIN','').rstrip('/'),'stats':build_stats(threads,hist,outcomes),
            'outbox':s.rows('SELECT id,status,attempts,error FROM outbox'),
            'metrics':s.rows('SELECT name,SUM(value) AS total,COUNT(*) AS samples FROM metrics GROUP BY name')}
class Flags(BaseModel):
    paused:bool|None=None
    archived:bool|None=None
@app.post('/api/threads/{thread_id}/flags')
def flags(thread_id:str,body:Flags):
    try:s.set_thread_flags(thread_id,paused=body.paused,archived=body.archived)
    except KeyError:raise HTTPException(404,'Thread not found')
    rt.audit(thread_id,'flags_changed','Owner updated thread controls');return {'ok':True}
@app.post('/api/mock/threads/{thread_id}/simulate-visibility')
def visibility(thread_id:str,visible:bool):
    t=service.thread_by_id(thread_id)
    if not t or t['platform']!='simulator':raise HTTPException(404,'Simulator thread not found')
    s.set_thread_flags(thread_id,visibility='available' if visible else 'not_observed');return {'ok':True}
class Incoming(BaseModel):
    body:str=Field(min_length=1,max_length=2000)
@app.post('/api/mock/threads/{thread_id}/incoming')
def incoming(thread_id:str,body:Incoming):
    t=service.thread_by_id(thread_id)
    if not t or t['platform']!='simulator':raise HTTPException(404,'Simulator thread not found')
    ident='incoming-'+secrets.token_hex(12)
    with s.connect() as db:db.execute('INSERT INTO source_messages VALUES(?,?,?,?,?)',(ident,thread_id,'them',body.body,s.utcnow()))
    return {'message_id':ident}
@app.post('/api/drafts/{draft_id}/reject')
def reject(draft_id:int):
    d=s.draft_by_id(draft_id)
    if not d:raise HTTPException(404,'Draft not found')
    if d['status']!='pending':raise HTTPException(409,'Draft resolved')
    s.set_draft_status(draft_id,'rejected');return {'ok':True}
@app.post('/api/drafts/{draft_id}/approve')
async def approve(draft_id:int,request:Request):
    """Owner sends a draft, optionally after editing it. The owner is the author of what goes out."""
    try:payload=await request.json()
    except ValueError:payload=None
    edited=payload.get('body') if isinstance(payload,dict) else None
    if edited is not None:
        edited=str(edited).strip()
        if not 1<=len(edited)<=1000:raise HTTPException(422,'Wiadomość musi mieć od 1 do 1000 znaków.')
    try:
      async with service.owner_lock():
        if edited is not None:
            with s.connect() as db:
                if db.execute("UPDATE drafts SET body=? WHERE id=? AND status='pending'",(edited,draft_id)).rowcount!=1:
                    raise HTTPException(409,'Draft already resolved or unavailable')
            rt.audit(None,'draft_edited','Owner edited a draft before sending')
        try:return await service.execute(draft_id)
        except DispatchDenied as e:raise HTTPException(409,str(e))
        except PermissionError as e:raise HTTPException(403,str(e))
    except service.Busy as e:raise HTTPException(409,str(e))
class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:__import__('typing').Literal['simulation','supervised','authorized_autonomy']='supervised'
    paused:bool=False
    language:str=Field(default='auto',max_length=30)
    style:str=Field(default=rt.DEFAULT_STYLE,max_length=1000)
    profile:dict[str,str]=Field(default_factory=dict,max_length=30)
    feedback:list[str]=Field(default_factory=list,max_length=20)
    email:bool=False
    retention_days:int=Field(default=365,ge=1,le=365)
    goal:__import__('typing').Literal['date','date_or_instagram','instagram','chat']='date'
    allow_instagram:bool=True
    pace:__import__('typing').Literal['slow','normal','fast']='normal'
    availability:str=Field(default='zwykle wieczory w tygodniu, w weekend elastycznie',max_length=300)
    date_ideas:list[str]=Field(default_factory=list,max_length=12)
_BACKGROUND=set()  # strong references to follow-up tasks still waiting for the bot
@app.put('/api/settings')
async def settings(body:Settings):
    if any(len(v)>1000 or len(k)>100 for k,v in body.profile.items()) or any(len(f)>500 for f in body.feedback):raise HTTPException(422,'Setting too long')
    # Saving never waits for the bot: a click on "Pause" or a new style must not fail with "busy" while a draft is
    # being written. Settings are one quick row; anything already in flight re-checks them (settings hash) before
    # it sends, so a draft written with the old style becomes stale instead of going out.
    before=rt.settings_hash()
    rt.save_settings(body.model_dump())
    changed=rt.settings_hash()!=before
    async def follow_up():
        async with service.LOCK:
            # Re-evaluate queued autonomy eligibility without regenerating/repeating sent actions.
            with s.connect() as db:db.execute("UPDATE jobs SET status='queued',available=0 WHERE status IN ('done','cancelled','blocked') AND anchor IN (SELECT anchor_message_id FROM drafts WHERE status='pending')")
            # New style, facts or goals: waiting drafts are rewritten now instead of turning out of date.
            n=rt.regenerate_pending() if changed else 0
        service.WAKE.set()
        return n
    regenerating=0;task=asyncio.create_task(follow_up())
    try:regenerating=await asyncio.wait_for(asyncio.shield(task),3)
    except asyncio.TimeoutError:_BACKGROUND.add(task);task.add_done_callback(_BACKGROUND.discard)  # finishes once the bot is free
    return {'ok':True,'regenerating':regenerating,'saved':True}
class Grant(BaseModel):
    enabled:bool=False
    participant_consent:bool=False
    disclosed:bool=False
@app.put('/api/threads/{thread_id}/grant')
def grant(thread_id:str,body:Grant):
    if not service.thread_by_id(thread_id):raise HTTPException(404,'Thread not found')
    with s.connect() as db:db.execute('INSERT OR REPLACE INTO grants VALUES(?,?,?,?)',(thread_id,int(body.enabled),int(body.participant_consent),int(body.disclosed)))
    with s.connect() as db:db.execute("UPDATE jobs SET status='queued',available=0 WHERE thread_id=? AND status IN ('done','cancelled','blocked') AND anchor IN (SELECT anchor_message_id FROM drafts WHERE status='pending')",(thread_id,))
    rt.audit(thread_id,'permission_changed','Owner changed automation consent/disclosure grant');return {'ok':True}
@app.delete('/api/threads/{thread_id}/grant')
def grant_reset(thread_id:str):
    """Back to the account default (e.g. the bio disclosure) for this conversation."""
    with s.connect() as db:db.execute('DELETE FROM grants WHERE thread_id=?',(thread_id,))
    rt.audit(thread_id,'permission_changed','Owner reset this conversation to the account automation default');return {'ok':True}
@app.post('/api/connections/{connection_id}/revoke')
def revoke(connection_id:str):
    with s.connect() as db:
        db.execute('UPDATE connections SET enabled=0 WHERE id=?',(connection_id,))
        db.execute('UPDATE grants SET enabled=0 WHERE thread_id IN (SELECT id FROM threads WHERE connection_id=?)',(connection_id,))
    return {'ok':True}
@app.delete('/api/threads/{thread_id}')
async def delete(thread_id:str):
    async with service.LOCK:rt.delete_thread(thread_id)
    return {'ok':True}
@app.post('/webhooks/telegram')
async def telegram(request:Request):
    secret=os.getenv('TELEGRAM_WEBHOOK_SECRET','')
    if len(secret)<24 or not same_secret(request.headers.get('x-telegram-bot-api-secret-token',''),secret):raise HTTPException(403,'Webhook secret required')
    if int(request.headers.get('content-length','0'))>100000:raise HTTPException(413,'Update too large')
    raw=await request.body()
    if len(raw)>100000:raise HTTPException(413,'Update too large')
    try:telegram_update(json.loads(raw))
    except PermissionError:raise HTTPException(403,'Business account not authorized')
    except (ValueError,KeyError,TypeError):raise HTTPException(422,'Malformed update')
    return {'ok':True}

@app.post('/api/threads/{thread_id}/regenerate')
async def regenerate(thread_id:str):
    try:
      async with service.owner_lock():
        t=service.thread_by_id(thread_id)
        if not t:raise HTTPException(404,'Thread not found')
        hist=s.messages(thread_id)
        if not hist:  # nothing written yet: a new first message
            r=campaigns.launch([thread_id],'draft')
            if thread_id in r['rejected']:raise HTTPException(409,r['rejected'][thread_id])
            service.WAKE.set();return {'ok':True}
        if hist[-1]['sender']!='them':raise HTTPException(409,'No incoming turn to answer')
        with s.connect() as db:
            d=db.execute('SELECT * FROM drafts WHERE thread_id=? AND anchor_message_id=?',(thread_id,hist[-1]['id'])).fetchone()
            if d:
                if db.execute('SELECT 1 FROM actions WHERE draft_id=?',(d['id'],)).fetchone():raise HTTPException(409,'Attempted action cannot be regenerated')
                db.execute("UPDATE drafts SET status='regenerate' WHERE id=?",(d['id'],))
            # updated=0: the owner's request goes to the front of the queue, ahead of drafts nobody asked for yet
            db.execute("UPDATE jobs SET status='queued',available=0,updated=0 WHERE thread_id=? AND anchor=?",(thread_id,hist[-1]['id']))
        rt.enqueue(thread_id,hist[-1]['id'])
    except service.Busy as e:raise HTTPException(409,str(e))
    service.WAKE.set()
    return {'ok':True}

class Launch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    thread_ids:list[str]=Field(min_length=1,max_length=100)
    mode:__import__('typing').Literal['auto','draft']='draft'
@app.post('/api/campaigns')
def campaign_launch(body:Launch):
    """Start a campaign: the agent writes the first message to the chosen new matches (and sends it in 'auto' mode)."""
    if not model_configured():raise HTTPException(409,'Podłącz model AI, żeby agent mógł pisać pierwsze wiadomości.')
    r=campaigns.launch(body.thread_ids,body.mode)
    if not r['accepted']:raise HTTPException(409,next(iter(r['rejected'].values()),'Nie ma czego uruchomić.'))
    service.WAKE.set();return r
@app.post('/api/campaigns/stop')
def campaign_stop():
    return {'stopped':campaigns.stop()}
class OpenerMode(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:__import__('typing').Literal['auto','draft']='draft'
@app.post('/api/threads/{thread_id}/opener')
def thread_opener(thread_id:str,body:OpenerMode=OpenerMode()):
    """One conversation: the agent writes the first message and leaves it as a draft (or sends it, in 'auto' mode)."""
    if not model_configured():raise HTTPException(409,'Podłącz model AI, żeby agent mógł pisać pierwsze wiadomości.')
    r=campaigns.launch([thread_id],body.mode)
    if thread_id in r['rejected']:raise HTTPException(409,r['rejected'][thread_id])
    service.WAKE.set();return r

class TinderConnect(BaseModel):
    model_config=ConfigDict(extra='forbid')
    account_owned:bool
    acknowledge_unofficial:bool

@app.post('/api/tinder/connect')
async def tinder_connect(body:TinderConnect):
    from agent.tinder import connect,TinderAuthError,TinderError
    if not body.account_owned or not body.acknowledge_unofficial:
        raise HTTPException(422,'Account ownership and unofficial integration acknowledgement required')
    async with service.LOCK:
        try:cid=await connect()
        except TinderAuthError as exc:
            detail='Tinder denied inbox access (HTTP 401). Reconnect with the current token from your own working Tinder inbox. Profile access alone is insufficient.' if str(exc)=='inbox_access_denied' else str(exc)
            raise HTTPException(403,detail)
        except TinderError as exc:raise HTTPException(503,str(exc))
    return {'connection_id':cid,'unofficial':True,'automatic_sending':True,
            'scope':'Consented and disclosed threads; no per-message approval'}

_BG=set()
@app.post('/api/tinder/restore-deleted')
async def tinder_restore_deleted():
    """One click: keep conversations (retention >= 365 days), allow re-import, then sync in the background."""
    from agent.tinder import poll,clear_local_budget_block
    async with service.LOCK:
        cfg=rt.settings()
        if cfg.get('retention_days',30)<365:rt.save_settings({**cfg,'retention_days':365})
        with s.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            n=db.execute("DELETE FROM tombstones WHERE thread_id LIKE 'tinder:%'").rowcount
        clear_local_budget_block()
    rt.audit(None,'tinder_reimport_allowed','Owner allowed re-import of deleted Tinder conversations: %d'%n)
    async def run():
        async with service.SYNC:await poll()
        service.WAKE.set()
    task=asyncio.create_task(run());_BG.add(task);task.add_done_callback(_BG.discard)
    return {'restored':n,'retention_days':365,'sync':'started'}

@app.get('/api/style')
def style_library():
    from agent import style
    return style.library_summary()

_TOKEN_ATTEMPTS=[]
@app.post('/api/tinder/token')
async def tinder_token_save(request:Request):
    """Customer pastes their Tinder session token. Verified against Tinder, then stored encrypted; never echoed."""
    from agent import vault
    from agent.tinder import TinderClient,TinderAuthError,TinderError,valid_token_format,TOKEN_SLOT,connect
    now=time.time();_TOKEN_ATTEMPTS[:]=[t for t in _TOKEN_ATTEMPTS if t>now-3600]
    if len(_TOKEN_ATTEMPTS)>=10:raise HTTPException(429,'Za dużo prób. Spróbuj za godzinę.')
    _TOKEN_ATTEMPTS.append(now)
    try:body=await request.json()
    except ValueError:raise HTTPException(422,'Nieprawidłowe dane')
    value=str(body.get('token','')).strip().strip('"').strip("'") if isinstance(body,dict) else ''
    if not (isinstance(body,dict) and body.get('account_owned') is True and body.get('acknowledge_unofficial') is True):
        raise HTTPException(422,'Potwierdź, że to Twoje konto i że integracja jest nieoficjalna')
    if body.get('sensitive_data') is not True:
        raise HTTPException(422,'Potrzebujemy Twojej wyraźnej zgody na przetwarzanie danych z aplikacji randkowej (art. 9 RODO).')
    if not valid_token_format(value):raise HTTPException(422,'To nie wygląda na token Tindera. Skopiuj wartość TinderWeb/APIToken.')
    if not vault.available():raise HTTPException(503,'Serwer nie ma klucza szyfrowania (TOKEN_ENCRYPTION_KEY). Token nie został zapisany.')
    async with service.LOCK:
        try:
            async with TinderClient(value) as api:
                api.reconnect=True
                await api.profile();await api.check_inbox_access()
        except TinderAuthError:
            raise HTTPException(403,'Tinder odrzucił ten token. Zaloguj się ponownie na tinder.com i skopiuj nowy.')
        except TinderError:
            raise HTTPException(503,'Nie udało się sprawdzić tokena w Tinderze. Spróbuj za chwilę.')
        vault.put(TOKEN_SLOT,value);value=None
        rt.audit(None,'tinder_token_saved','Encrypted Tinder token saved by owner; explicit art. 9 GDPR consent given')
        try:cid=await connect()
        except TinderError as exc:raise HTTPException(503,str(exc))
    # Right after connecting, copy the owner's own Tinder interests into the empty "zainteresowania" fact.
    # Best effort: a failure here (limit, Tinder hiccup) must never break connecting; the settings button still works.
    interests=[]
    try:
        from agent.tinder import sync_profile
        r=await sync_profile(cid);interests=r['interests']
        if r['filled']:_regenerate_in_background()
    except Exception:pass
    return {'connected':True,'connection_id':cid,'interests':interests}

@app.delete('/api/tinder/token')
async def tinder_token_delete():
    from agent import vault
    from agent.tinder import TOKEN_SLOT
    async with service.LOCK:
        vault.delete(TOKEN_SLOT)
        with s.connect() as db:db.execute("UPDATE connections SET enabled=0 WHERE id LIKE 'tinder:%'")
    rt.audit(None,'tinder_token_deleted','Owner removed the stored Tinder token; connection disabled')
    return {'deleted':True}

def _regenerate_in_background():
    """Facts changed: waiting drafts are rewritten once the bot is free."""
    async def follow_up():
        async with service.LOCK:rt.regenerate_pending()
        service.WAKE.set()
    task=asyncio.create_task(follow_up());_BACKGROUND.add(task);task.add_done_callback(_BACKGROUND.discard)

async def _owner_read(connection_id:str,read):
    """Owner-clicked reads of their own Tinder profile: one place that turns Tinder errors into plain Polish."""
    from agent.tinder import status_update,is_local_limit,TinderAuthError,TinderRateLimited,TinderRestriction,TinderError
    try:return await read(connection_id)
    except TinderRestriction:
        status_update(connection_id,error='restriction_requires_manual_review',disable=True)
        raise HTTPException(409,'Tinder chce, żebyś sprawdził konto w oficjalnej aplikacji. Połączenie wstrzymane.')
    except TinderRateLimited as exc:
        # Our own request budget is not Tinder asking for a pause: say which one it is.
        if is_local_limit(exc):raise HTTPException(429,'Winq robi teraz dużo zapytań do Tindera i chwilowo wstrzymał sprawdzanie. Spróbuj za minutę.')
        raise HTTPException(429,'Tinder poprosił o przerwę. Spróbuj za kilka minut.')
    except TinderAuthError:raise HTTPException(409,'Połączenie z Tinderem wygasło. Wklej nowy token w Ustawienia → Tinder.')
    except TinderError:raise HTTPException(502,'Nie udało się teraz odczytać profilu z Tindera. Spróbuj za chwilę.')

@app.post('/api/tinder/connections/{connection_id}/check-bio')
async def tinder_check_bio(connection_id:str):
    """Reads the owner's own bio now, so the AI-disclosure step answers at once instead of at the next sync."""
    from agent.tinder import check_bio
    return await _owner_read(connection_id,check_bio)

@app.post('/api/tinder/connections/{connection_id}/sync-profile')
async def tinder_sync_profile(connection_id:str):
    """Separate from the inbox sync: reads the owner's own profile (interests) and fills the empty "zainteresowania" fact."""
    from agent.tinder import sync_profile
    r=await _owner_read(connection_id,sync_profile)
    if r['filled']:_regenerate_in_background()
    return r

@app.post('/api/tinder/sync')
async def tinder_sync():
    from agent.tinder import poll
    if service.SYNC.locked():raise HTTPException(409,'Synchronizacja już trwa')
    async with service.SYNC:await poll()
    service.WAKE.set()
    return {'ok':True}

@app.get('/static/{name:path}')
def static_file(name:str):
    if name not in STATIC_FILES:raise HTTPException(404,'Static resource not found')
    return FileResponse(BASE/'static'/name,media_type=STATIC_FILES[name])

class TinderAutomation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool|None=None
    bio_mode:bool|None=None

@app.put('/api/tinder/connections/{connection_id}/automation')
def tinder_automation(connection_id:str,body:TinderAutomation):
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT value FROM connections WHERE id=? AND id LIKE 'tinder:%'",(connection_id,)).fetchone()
        if not row:raise HTTPException(404,'Tinder connection not found')
        value=json.loads(row['value'])
        if body.enabled:
            from agent import plans
            if not plans.autopilot_allowed():raise HTTPException(403,'Autopilot jest w pakietach Flirt i Casanova. Zmień pakiet na stronie konta.')
        if body.enabled is not None:value['auto_send']=body.enabled
        if body.bio_mode is not None:value['bio_mode']=body.bio_mode
        db.execute('UPDATE connections SET value=? WHERE id=?',(json.dumps(value),connection_id))
        if value.get('auto_send'):
            db.execute("UPDATE jobs SET status='queued',available=0 WHERE status IN ('done','blocked','cancelled') AND thread_id IN (SELECT id FROM threads WHERE connection_id=?) AND anchor IN (SELECT anchor_message_id FROM drafts WHERE status='pending')",(connection_id,))
    rt.audit(None,'tinder_automation_changed','Owner changed account automatic sending')
    return {'ok':True,'automatic_sending':bool(value.get('auto_send')),'bio_mode':bool(value.get('bio_mode'))}

# Outermost boundary also covers login, errors and unauthenticated requests.
app.add_middleware(SecurityBoundary)
