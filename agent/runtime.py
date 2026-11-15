"""Durable local control plane. One installation = one owner, explicit platform grants."""
import hashlib
import json
import os
import re
import time
from uuid import uuid4
from agent import storage as s

LEGACY_STYLE='short, casual; no forced questions or emoji'
DEFAULT_STYLE=('krótko, zwykle około 30 znaków, jedno-dwa zdania, od małej litery, bez emoji, pytanie tylko gdy naturalne, '
               'bez serii pytań, reaguj konkretnie na to, co napisała, lekki humor, bez komplementów na siłę')
DEFAULT_DATE_IDEAS=['kawa albo matcha na mieście','spacer z kawą na wynos','piwo albo wino w luźnym barze',
                    'wystawa, targi albo coś w tym stylu','planszówki w barze','lody albo gofry i spacer']
DEFAULTS = {'mode':'supervised','paused':False,'language':'auto','style':DEFAULT_STYLE,
            'profile':{},'feedback':[], 'email':False,'retention_days':365,
            'goal':'date','allow_instagram':True,'pace':'normal',
            'availability':'zwykle wieczory w tygodniu, w weekend elastycznie','date_ideas':DEFAULT_DATE_IDEAS}

def init():
    s.init_db()
    with s.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS model_calls (id INTEGER PRIMARY KEY, ts REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS grants (thread_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            participant_consent INTEGER NOT NULL DEFAULT 0, disclosed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, anchor TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL DEFAULT 0,
            updated REAL NOT NULL, error TEXT, UNIQUE(thread_id,anchor));
        CREATE TABLE IF NOT EXISTS draft_context (draft_id INTEGER PRIMARY KEY, settings_hash TEXT NOT NULL, history_hash TEXT);
        CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, draft_id INTEGER UNIQUE NOT NULL,
            thread_id TEXT NOT NULL, anchor TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT, updated REAL NOT NULL, automatic INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS memory (thread_id TEXT NOT NULL, source_id TEXT NOT NULL, kind TEXT NOT NULL,
            value TEXT NOT NULL, status TEXT NOT NULL, confidence TEXT NOT NULL DEFAULT 'explicit',
            PRIMARY KEY(thread_id,source_id,kind));
        CREATE TABLE IF NOT EXISTS outcome_state (thread_id TEXT PRIMARY KEY, anchor TEXT NOT NULL, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, notification_id INTEGER UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL DEFAULT 0,
            error TEXT);
        CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, thread_id TEXT,
            event TEXT NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metrics (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, name TEXT NOT NULL, value REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS connections (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, can_reply INTEGER NOT NULL,
            user_id TEXT NOT NULL, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS updates (id INTEGER PRIMARY KEY, received TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tombstones (thread_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS tinder_requests (id INTEGER PRIMARY KEY, ts REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tinder_threads (thread_id TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tinder_receipts (action_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, message_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS leases (name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
        ''')
        db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)',(json.dumps(DEFAULTS),))
        actioncols={r[1] for r in db.execute('PRAGMA table_info(actions)')}
        if 'automatic' not in actioncols:db.execute('ALTER TABLE actions ADD COLUMN automatic INTEGER NOT NULL DEFAULT 0')
        ctxcols={r[1] for r in db.execute('PRAGMA table_info(draft_context)')}
        if 'history_hash' not in ctxcols:db.execute('ALTER TABLE draft_context ADD COLUMN history_hash TEXT')
        receiptcols={r[1] for r in db.execute('PRAGMA table_info(tinder_receipts)')}
        if 'next_check' not in receiptcols:db.execute('ALTER TABLE tinder_receipts ADD COLUMN next_check REAL NOT NULL DEFAULT 0')
        # Local simulator send IDs provide exactly-once behavior across browser failures.
        db.execute('CREATE TABLE IF NOT EXISTS sim_receipts (action_id TEXT PRIMARY KEY, message_id TEXT NOT NULL)')
        cols={r[1] for r in db.execute('PRAGMA table_info(threads)')}
        for name,definition in [('platform',"TEXT NOT NULL DEFAULT 'simulator'"),('connection_id',"TEXT"),('chat_id','TEXT')]:
            if name not in cols: db.execute(f'ALTER TABLE threads ADD COLUMN {name} {definition}')

def recover():
    with s.connect() as db:
        db.execute("UPDATE drafts SET status='uncertain' WHERE id IN (SELECT draft_id FROM actions WHERE status='sending')")
        db.execute("UPDATE actions SET status='uncertain' WHERE status='sending'")
        db.execute("UPDATE jobs SET status='queued' WHERE status='processing'")
        db.execute("UPDATE outbox SET status='uncertain' WHERE status='sending'")

def settings():
    stored=json.loads(s.rows('SELECT value FROM settings WHERE id=1')[0]['value'])
    # Values that were only the old shipped defaults are upgraded; anything the owner typed is kept.
    if stored.get('style')==LEGACY_STYLE:stored.pop('style')
    if not stored.get('date_ideas'):stored.pop('date_ideas',None)
    if stored.get('retention_days')==30:stored.pop('retention_days')
    return {**DEFAULTS,**stored}
def save_settings(value):
    with s.connect() as db: db.execute('UPDATE settings SET value=? WHERE id=1',(json.dumps(value,ensure_ascii=False),))
    audit(None,'settings_changed','Owner updated configuration')

def audit(thread,event,detail):
    # Only controlled metadata. Never record exception repr or provider response bodies.
    with s.connect() as db:
        db.execute('INSERT INTO activity(ts,thread_id,event,detail) VALUES(?,?,?,?)',(s.utcnow(),thread,event,detail[:500]))
    print(json.dumps({'event':event,'thread_id':thread,'ts':s.utcnow()}),flush=True)

def metric(name,value=1):
    with s.connect() as db: db.execute('INSERT INTO metrics(ts,name,value) VALUES(?,?,?)',(s.utcnow(),name,value))

def enqueue(thread,anchor):
    key=hashlib.sha256(f'{thread}:{anchor}'.encode()).hexdigest()
    with s.connect() as db:
        db.execute('INSERT OR IGNORE INTO jobs(id,thread_id,anchor,updated) VALUES(?,?,?,?)',(key,thread,anchor,time.time()))
        db.execute("UPDATE jobs SET status='queued',available=0 WHERE id=? AND status IN ('cancelled','blocked')",(key,))

def claim():
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        r=db.execute("SELECT * FROM jobs WHERE status='queued' AND available<=? ORDER BY updated LIMIT 1",(time.time(),)).fetchone()
        if not r:return None
        db.execute("UPDATE jobs SET status='processing',attempts=attempts+1,updated=? WHERE id=?",(time.time(),r['id']))
        return dict(r)

def job_end(job,status,error=None):
    with s.connect() as db:
        db.execute('UPDATE jobs SET status=?,error=?,available=?,updated=? WHERE id=?',
                   (status,error,time.time()+min(300,2**min(job['attempts']+1,8)),time.time(),job['id']))

def _connection(connection_id,ctx):
    key=('connection',connection_id)
    if key not in ctx:
        found=s.rows('SELECT * FROM connections WHERE id=?',(connection_id,))
        ctx[key]=found[0] if found else None
    return ctx[key]

def eligible(thread,ctx=None):
    """May the agent prepare drafts here and may the owner send one he approved? (Owner reviews every message.)
    Sending without the owner's click is a separate, stricter gate: auto_allowed().
    ctx is an optional per-request cache, so a listing of hundreds of threads does not re-read the same settings
    and connection for each of them."""
    ctx={} if ctx is None else ctx
    cfg=ctx['cfg'] if 'cfg' in ctx else ctx.setdefault('cfg',settings())
    if thread.get('platform') not in (None,'simulator'):
        con=_connection(thread['connection_id'],ctx)
        if not con or not con['enabled'] or not con['can_reply']:return False
    if thread.get('platform') == 'telegram':
        # Telegram participants talk to a bot account directly: nothing is generated before their consent.
        grants=s.rows('SELECT * FROM grants WHERE thread_id=?',(thread['id'],))
        if not grants or not all(grants[0][k] for k in ('enabled','participant_consent','disclosed')):return False
    if thread.get('platform') == 'tinder':
        key=('tinder_ok',thread['connection_id'])
        if key not in ctx:
            from agent.tinder import connection, TinderError
            try: connection(thread['connection_id']);ctx[key]=True
            except TinderError: ctx[key]=False
        if not ctx[key]:return False
    return not cfg['paused'] and not thread['user_paused'] and not thread['user_archived'] and thread['source_visibility']=='available'

AI_MENTION=re.compile(r"(?<![\w])(ai|a\.i\.|bot\w*|chat\s?gpt|sztuczn\w*)(?![\w])",re.I)
AI_OBJECTION=re.compile(r"(nie\s+(chc\w*|lubi\w*|pisz\w*|b[eę]d\w*\s+pisa\w*)|s[łl]abe|dziwn\w*|creepy|weird|cringe|[żz]enad\w*|"
                        r"wol[eę]\s+(cz[łl]owiek|normaln)|serio\s+bot|kurwa|stop|not\s+ok|don'?t\s+like|no\s+thanks)",re.I)


def ai_objection(text):
    """She objects to talking with AI (not just asking about it)."""
    return bool(text) and bool(AI_MENTION.search(text)) and bool(AI_OBJECTION.search(text))


def ai_question(text):
    return bool(text) and bool(AI_MENTION.search(text))


def auto_consent(thread,ctx=None):
    """Has the other person been told that AI is used here? Either an explicit per-conversation grant from the owner,
    or the owner's Tinder bio says so (checked on every sync). If she asks, the reply admits it honestly (see
    service.process_job); if she objects, the conversation goes back to the owner. The owner can switch any off."""
    ctx={} if ctx is None else ctx
    if 'grants' in ctx:grants=[ctx['grants'][thread['id']]] if thread['id'] in ctx['grants'] else []
    else:grants=s.rows('SELECT * FROM grants WHERE thread_id=?',(thread['id'],))
    if grants and all(grants[0][k] for k in ('enabled','participant_consent','disclosed')):return True
    if grants:return False  # owner set this conversation explicitly (e.g. switched autopilot off)
    if thread.get('platform')!='tinder':return False
    con=_connection(thread['connection_id'],ctx)
    value=json.loads(con['value']) if con else {}
    if not (value.get('bio_mode') and value.get('bio_disclosure')):return False
    history=ctx.get('hist',{}).get(thread['id']) if ctx.get('hist') is not None else None
    if history is None:history=s.messages(thread['id'])
    if any(m['sender']=='them' and ai_objection(m['body'] or '') for m in history):
        with s.connect() as db:db.execute('INSERT OR IGNORE INTO grants VALUES(?,?,?,?)',(thread['id'],0,0,0))
        audit(thread['id'],'autopilot_handed_to_owner','She objected to AI; this conversation now needs the owner')
        return False
    return True


def auto_allowed(thread,ctx=None):
    ctx={} if ctx is None else ctx
    cfg=ctx['cfg'] if 'cfg' in ctx else ctx.setdefault('cfg',settings())
    if not eligible(thread,ctx):return False
    if thread['platform']=='simulator':return cfg['mode']=='simulation'
    con=_connection(thread['connection_id'],ctx)
    platform_auto=cfg['mode']=='authorized_autonomy'
    if thread['platform']=='tinder':
        platform_auto=cfg['mode']!='simulation' and bool(con and json.loads(con['value']).get('auto_send',False))
    return bool(platform_auto and auto_consent(thread,ctx) and con and con['enabled'] and con['can_reply'])

def retain(thread,history):
    """Store bounded, source-linked observations, never convert questions to facts.
    Rich semantic facts can be supplied separately only with evidence validation.
    """
    with s.connect() as db:
        for m in history:
            text=m['body'];lower=text.lower()
            kind='boundary' if any(x in lower for x in ("don't contact",'nie pisz','not interested','nie jestem zainteres')) else 'observation'
            if kind=='observation':
                if re.search(r'nie dam rady|odwoł|cancel|can.t make',lower):kind='cancellation'
                elif '?' in text:kind='question_or_suggestion'
                elif re.search(r'\b(może|chyba|maybe|perhaps|not sure)\b',lower):kind='uncertainty'
            if m['sender']!='them':continue
            # Observations explicitly preserve speaker and exact text, not inferred biography.
            db.execute('INSERT OR IGNORE INTO memory(thread_id,source_id,kind,value,status) VALUES(?,?,?,?,?)',
                       (thread,m['id'],kind,text[:600],'explicit_observation'))
        db.execute('DELETE FROM memory WHERE thread_id=? AND source_id NOT IN (SELECT source_id FROM memory WHERE thread_id=? ORDER BY rowid DESC LIMIT 24)',(thread,thread))

def memory(thread): return s.rows('SELECT * FROM memory WHERE thread_id=? ORDER BY rowid DESC LIMIT 24',(thread,))

def memory_by_thread():
    """The same 24 newest observations per thread as memory(), for every thread in one query."""
    out={}
    for r in s.rows('SELECT * FROM memory ORDER BY rowid DESC'):
        mine=out.setdefault(r['thread_id'],[])
        if len(mine)<24:mine.append(r)
    return out

def record_outcomes(thread,anchor,outcomes):
    value=json.dumps([o.as_dict() for o in outcomes],ensure_ascii=False)
    with s.connect() as db:
        db.execute('INSERT OR REPLACE INTO outcome_state VALUES(?,?,?)',(thread,anchor,value))
        for o in outcomes:
            if o.kind not in ('date_confirmed','date_cancelled','date_rescheduled','instagram_shared','phone_shared'):continue
            c=db.execute('INSERT OR IGNORE INTO notifications(thread_id,kind,fingerprint,body,created_at) VALUES(?,?,?,?,?)',
                         (thread,o.kind,o.fingerprint,o.body,s.utcnow()))
            if c.rowcount:
                db.execute('INSERT INTO outbox(notification_id) VALUES(?)',(c.lastrowid,))

def delete_thread(thread):
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR IGNORE INTO tombstones VALUES(?)',(thread,))
        db.execute('DELETE FROM outbox WHERE notification_id IN (SELECT id FROM notifications WHERE thread_id=?)',(thread,))
        for table in ('messages','source_messages','drafts','notifications','jobs','actions','memory','outcome_state','grants','activity','tinder_threads','tinder_receipts'):
            db.execute(f'DELETE FROM {table} WHERE thread_id=?',(thread,))
        db.execute('DELETE FROM draft_context WHERE draft_id NOT IN (SELECT id FROM drafts)')
        db.execute('DELETE FROM sim_receipts WHERE message_id NOT IN (SELECT id FROM source_messages)')
        db.execute('DELETE FROM threads WHERE id=?',(thread,))
    audit(None,'data_deleted','Conversation and related records deleted; source reimport blocked')

def expire():
    from datetime import datetime,timedelta,timezone
    cutoff=(datetime.now(timezone.utc)-timedelta(days=settings()['retention_days'])).isoformat()
    for t in s.threads():
        recent=s.rows('SELECT MAX(created_at) AS ts FROM messages WHERE thread_id=?',(t['id'],))[0]['ts']
        if recent and recent<cutoff: delete_thread(t['id'])
    with s.connect() as db:
        db.execute('DELETE FROM activity WHERE ts<?',(cutoff,));db.execute('DELETE FROM metrics WHERE ts<?',(cutoff,))
        db.execute('DELETE FROM updates WHERE received<?',(cutoff,))
        db.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
        db.execute('DELETE FROM model_calls WHERE ts<?',(time.time()-3600,))
        db.execute('DELETE FROM tinder_requests WHERE ts<?',(time.time()-3600,))


def settings_hash(cfg=None):
    cfg=settings() if cfg is None else cfg
    value={k:cfg.get(k) for k in ('profile','style','language','feedback','goal','allow_instagram','pace','availability','date_ideas')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def regenerate_pending():
    """After the owner changes style, facts or goals, drafts waiting for an answer are written again with the new
    settings (otherwise they would just turn out of date). Only drafts for the latest incoming message that were
    never attempted to be sent. Returns how many were queued."""
    n=0
    for d in s.all_drafts():
        if d['status'] not in ('pending','stale'):continue
        hist=s.messages(d['thread_id'])
        if not hist or hist[-1]['id']!=d['anchor_message_id'] or hist[-1]['sender']!='them':continue
        with s.connect() as db:
            if db.execute('SELECT 1 FROM actions WHERE draft_id=?',(d['id'],)).fetchone():continue
            db.execute("UPDATE drafts SET status='regenerate' WHERE id=?",(d['id'],))
            db.execute("UPDATE jobs SET status='queued',available=0,updated=1 WHERE thread_id=? AND anchor=?",(d['thread_id'],d['anchor_message_id']))
        enqueue(d['thread_id'],d['anchor_message_id']);n+=1
    return n


def history_hash(history):
    return hashlib.sha256(json.dumps([{k:m[k] for k in ('id','sender','body','created_at')} for m in history],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
