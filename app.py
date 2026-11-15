"""Single-owner authorized conversation agent. Run one ASGI worker per database."""
import asyncio,contextlib,json,os,secrets,time
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse,HTMLResponse
from pydantic import BaseModel,Field,ConfigDict
from agent import storage as s,runtime as rt,service,tinder as tinder_integration
from agent.auth import token,same_secret,create_session,session_valid,revoke_session
from agent.http_security import SecurityBoundary,internal_request,public_origin
from agent.dispatch import DispatchDenied
from agent.llm import configured as model_configured
from agent.diagnostics import report_failure,tinder_startup_check
from agent.adapters import StaleAction,sim_send,telegram_update
from agent.triage import project
BASE=Path(__file__).resolve().parent
LOGIN='''<!doctype html><title>Conversation Agent · Sign in</title><style>body{font:17px system-ui;background:#f4f5f7;max-width:420px;margin:15vh auto}input,button{font:inherit;padding:12px;margin:8px 0;width:100%;box-sizing:border-box}small{color:#666}</style><h1>Conversation Agent</h1><p>Sign in with your dashboard access token.</p><form><input type=password autocomplete=current-password required aria-label="Access token"><button>Sign in</button></form><small>The local token is stored in runtime/dashboard-token. Set DASHBOARD_TOKEN for deployment.</small><p id=error></p><script src="/static/login.js" defer></script>'''
@asynccontextmanager
async def lifespan(app):
    public_origin();rt.init();token()
    # A process lease prevents independent workers reserving simultaneous browser sends.
    owner=secrets.token_hex(16)
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        prior=db.execute("SELECT * FROM leases WHERE name='coordinator'").fetchone()
        if prior and prior['expires']>time.time():raise RuntimeError('Another coordinator owns this database; use one ASGI worker')
        db.execute('INSERT OR REPLACE INTO leases VALUES(?,?,?)',('coordinator',owner,time.time()+120))
    rt.recover()
    async def heartbeat():
        while True:
            with s.connect() as db:db.execute("UPDATE leases SET expires=? WHERE name='coordinator' AND owner=?",(time.time()+120,owner))
            await asyncio.sleep(20)
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
    if path not in ('/health','/auth/login','/webhooks/telegram','/static/login.js'):
        auth=request.headers.get('authorization','')
        authenticated=same_secret(auth[7:],token()) if auth.startswith('Bearer ') else session_valid(request.cookies.get('agent_session',''))
        if not authenticated:
            return HTMLResponse(LOGIN,401) if path=='/' else JSONResponse({'detail':'Authentication required'},401)
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
@app.post('/auth/logout')
def logout(request:Request):
    revoke_session(request.cookies.get('agent_session',''))
    r=JSONResponse({'ok':True});r.delete_cookie('agent_session');return r
@app.get('/health')
def health():return {'status':'ok'}
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
    if service.LOCK.locked():raise HTTPException(409,'Coordinator busy')
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
    drafts=s.all_drafts();notes=s.notifications();rows=s.threads();hist={t['id']:s.messages(t['id']) for t in rows}
    outcomes={r['thread_id']:json.loads(r['value']) for r in s.rows('SELECT * FROM outcome_state')}
    from agent import strategy
    cfg=rt.settings()
    profiles={}
    for r in s.rows('SELECT thread_id,value FROM tinder_threads'):
        try:profiles[r['thread_id']]=json.loads(r['value']).get('profile')
        except ValueError:pass
    threads=[]
    for t in rows:
        p=project(t,hist[t['id']],[d for d in drafts if d['thread_id']==t['id']],[])
        p['outcomes']=[o['kind'] for o in outcomes.get(t['id'],[])];p['automatic_sending']=rt.auto_allowed(t);p['profile']=profiles.get(t['id']);h=hist[t['id']];p['sort_at']=(h[-1]['created_at'] if h else None) or (p['profile'] or {}).get('last_activity') or (p['profile'] or {}).get('matched_at') or '';p['matched_at']=(p['profile'] or {}).get('matched_at');p['plan']=strategy.analyze(hist[t['id']],cfg,outcomes.get(t['id'],[]));threads.append(p)
    return {'threads':threads,'messages':hist,'drafts':drafts,'notifications':notes,'llm_enabled':model_configured(),
            'worker':service.WORKER,'settings':rt.settings(),'grants':s.rows('SELECT * FROM grants'),
            'memory':{t['id']:rt.memory(t['id']) for t in rows},'outcome_details':outcomes,
            'activity':s.rows('SELECT * FROM activity ORDER BY id DESC LIMIT 100'),
            'actions':s.rows('SELECT * FROM actions ORDER BY updated DESC LIMIT 100'),
            'connections':s.rows('SELECT id,enabled,can_reply FROM connections'),
            'tinder':tinder_integration.public_status(),'stats':build_stats(threads,hist,outcomes),
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
async def approve(draft_id:int):
    if service.LOCK.locked():raise HTTPException(409,'Coordinator busy')
    async with service.LOCK:
        try:return await service.execute(draft_id)
        except DispatchDenied as e:raise HTTPException(409,str(e))
        except PermissionError as e:raise HTTPException(403,str(e))
class Settings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:__import__('typing').Literal['simulation','supervised','authorized_autonomy']='supervised'
    paused:bool=False
    language:str=Field(default='auto',max_length=30)
    style:str=Field(default='short, casual; no forced questions or emoji',max_length=1000)
    profile:dict[str,str]=Field(default_factory=dict,max_length=30)
    feedback:list[str]=Field(default_factory=list,max_length=20)
    email:bool=False
    retention_days:int=Field(default=30,ge=1,le=365)
    goal:__import__('typing').Literal['date','date_or_instagram','instagram','chat']='date'
    allow_instagram:bool=True
    pace:__import__('typing').Literal['slow','normal','fast']='normal'
    availability:str=Field(default='zwykle wieczory w tygodniu, w weekend elastycznie',max_length=300)
    date_ideas:list[str]=Field(default_factory=list,max_length=12)
@app.put('/api/settings')
def settings(body:Settings):
    if any(len(v)>1000 or len(k)>100 for k,v in body.profile.items()) or any(len(f)>500 for f in body.feedback):raise HTTPException(422,'Setting too long')
    rt.save_settings(body.model_dump())
    # Re-evaluate queued autonomy eligibility without regenerating/repeating sent actions.
    with s.connect() as db:db.execute("UPDATE jobs SET status='queued',available=0 WHERE status IN ('done','cancelled','blocked') AND anchor IN (SELECT anchor_message_id FROM drafts WHERE status='pending')")
    return {'ok':True}
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
    async with service.LOCK:
        t=service.thread_by_id(thread_id)
        if not t:raise HTTPException(404,'Thread not found')
        hist=s.messages(thread_id)
        if not hist or hist[-1]['sender']!='them':raise HTTPException(409,'No incoming turn to answer')
        with s.connect() as db:
            d=db.execute('SELECT * FROM drafts WHERE thread_id=? AND anchor_message_id=?',(thread_id,hist[-1]['id'])).fetchone()
            if d:
                if db.execute('SELECT 1 FROM actions WHERE draft_id=?',(d['id'],)).fetchone():raise HTTPException(409,'Attempted action cannot be regenerated')
                db.execute("UPDATE drafts SET status='regenerate' WHERE id=?",(d['id'],))
            db.execute("UPDATE jobs SET status='queued',available=0 WHERE thread_id=? AND anchor=?",(thread_id,hist[-1]['id']))
        rt.enqueue(thread_id,hist[-1]['id'])
    return {'ok':True}

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
        async with service.LOCK:await poll()
    task=asyncio.create_task(run());_BG.add(task);task.add_done_callback(_BG.discard)
    return {'restored':n,'retention_days':365,'sync':'started'}

@app.get('/api/style')
def style_library():
    from agent import style
    return {**style.library_summary(),'suggested_style':style.suggested_style()}

@app.post('/api/tinder/sync')
async def tinder_sync():
    from agent.tinder import poll
    if service.LOCK.locked():raise HTTPException(409,'Coordinator busy')
    async with service.LOCK:await poll()
    return {'ok':True}

@app.get('/static/{name}')
def static_script(name:str):
    if name not in ('dashboard.js','mock.js','login.js'):raise HTTPException(404,'Static resource not found')
    return FileResponse(BASE/'static'/name,media_type='text/javascript')

class TinderAutomation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool

@app.put('/api/tinder/connections/{connection_id}/automation')
def tinder_automation(connection_id:str,body:TinderAutomation):
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT value FROM connections WHERE id=? AND id LIKE 'tinder:%'",(connection_id,)).fetchone()
        if not row:raise HTTPException(404,'Tinder connection not found')
        value=json.loads(row['value']);value['auto_send']=body.enabled
        db.execute('UPDATE connections SET value=? WHERE id=?',(json.dumps(value),connection_id))
        if body.enabled:
            db.execute("UPDATE jobs SET status='queued',available=0 WHERE status IN ('done','blocked','cancelled') AND thread_id IN (SELECT id FROM threads WHERE connection_id=?) AND anchor IN (SELECT anchor_message_id FROM drafts WHERE status='pending')",(connection_id,))
    rt.audit(None,'tinder_automation_changed','Owner changed account automatic sending')
    return {'ok':True,'automatic_sending':body.enabled}

# Outermost boundary also covers login, errors and unauthenticated requests.
app.add_middleware(SecurityBoundary)
