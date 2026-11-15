"""Platform capability boundary; unofficial Tinder support is explicitly owner-enabled."""
import os,time,json
from typing import Protocol
from uuid import uuid4
import httpx
from agent import storage as s
from agent import runtime as rt

from agent.dispatch import DispatchDenied,guard

class StaleAction(DispatchDenied):pass
class UnsupportedPlatform(Exception):pass
class Adapter(Protocol):
    async def snapshot(self,thread:dict)->list[dict]: ...
    async def send(self,thread:dict,text:str,action_id:str,anchor:str)->str: ...
    async def reconcile(self,thread:dict,action_id:str)->str|None: ...

class FixtureAdapter:
    """Only deterministic tests; explicitly not browser execution."""
    async def snapshot(self,thread):return s.source_for_thread(thread['id'])
    async def send(self,thread,text,action_id,anchor):return sim_send(thread['id'],text,action_id,anchor)
    async def reconcile(self,thread,action_id):
        r=s.rows('SELECT message_id FROM sim_receipts WHERE action_id=?',(action_id,))
        return r[0]['message_id'] if r else None

def sim_send(thread,text,action,anchor):
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT message_id FROM sim_receipts WHERE action_id=?',(action,)).fetchone()
        if old:return old[0]
        meta=db.execute('SELECT * FROM threads WHERE id=?',(thread,)).fetchone()
        cfg=json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])
        if not meta or meta['platform']!='simulator' or cfg['paused'] or meta['user_paused'] or meta['user_archived'] or meta['source_visibility']!='available':raise PermissionError('Simulator permission revoked')
        reserved=db.execute('SELECT automatic FROM actions WHERE id=?',(action,)).fetchone()
        if reserved and reserved['automatic'] and cfg['mode']!='simulation':raise PermissionError('Autonomous simulation permission revoked')
        latest=db.execute('SELECT id FROM source_messages WHERE thread_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(thread,)).fetchone()
        if (latest['id'] if latest else '')!=anchor:raise StaleAction('New message invalidates draft')
        ident='sim-'+uuid4().hex
        db.execute('INSERT INTO source_messages VALUES(?,?,?,?,?)',(ident,thread,'you',text,s.utcnow()))
        db.execute('INSERT INTO sim_receipts VALUES(?,?)',(action,ident))
        return ident

class BrowserAdapter(FixtureAdapter):
    async def snapshot(self,thread):
        from agent.browser import read_mock_threads
        remote=await read_mock_threads()
        if thread['id'] not in remote:raise StaleAction('Thread absent from source')
        return remote[thread['id']]
    async def send(self,thread,text,action_id,anchor):
        from agent.browser import send_mock_approved
        result=await send_mock_approved(thread['id'],text,action_id,anchor)
        return result['message_id']

class TelegramAdapter:
    async def snapshot(self,thread):
        # Telegram Business webhooks expose updates, not a history-fetch API.
        return s.source_for_thread(thread['id'])
    async def reconcile(self,thread,action_id):return None # No server idempotency or arbitrary history fetch.
    async def send(self,thread,text,action_id,anchor):
        c=s.rows('SELECT * FROM connections WHERE id=?',(thread['connection_id'],))
        if not c or not c[0]['enabled'] or not c[0]['can_reply']:raise PermissionError('Business permission revoked')
        current=s.source_for_thread(thread['id'])
        guard(thread['id'],action_id,text,anchor,current)
        if not current or current[-1]['id']!=anchor:raise StaleAction()
        # Latest documented business reply rights and recency checked in addition to per-thread consent.
        from datetime import datetime,timezone
        incoming=[m for m in current if m['sender']=='them']
        if not incoming or (datetime.now(timezone.utc)-datetime.fromisoformat(incoming[-1]['created_at'])).total_seconds()>86400:
            raise PermissionError('Business reply window expired')
        key=os.getenv('TELEGRAM_BOT_TOKEN','')
        if not key:raise PermissionError('Telegram credentials missing')
        async with httpx.AsyncClient(timeout=20,trust_env=False,follow_redirects=False) as client:
            r=await client.post('https://api.telegram.org/bot'+key+'/sendMessage',json={
                'business_connection_id':thread['connection_id'],'chat_id':thread['chat_id'],'text':text})
            r.raise_for_status();data=r.json()
        if not data.get('ok') or not data.get('result',{}).get('message_id'):raise RuntimeError('Unverified send')
        result=data['result']
        if str(result.get('chat',{}).get('id'))!=thread['chat_id'] or result.get('text')!=text:
            raise RuntimeError('Receipt identity/content mismatch')
        if result.get('business_connection_id',thread['connection_id'])!=thread['connection_id']:
            raise RuntimeError('Receipt connection mismatch')
        ident=f"tg:{thread['connection_id']}:{thread['chat_id']}:{result['message_id']}"
        with s.connect() as db:
            db.execute('INSERT OR IGNORE INTO source_messages VALUES(?,?,?,?,?)',(ident,thread['id'],'you',text,s.utcnow()))
        return ident

def adapter(thread):
    if thread['platform']=='telegram':return TelegramAdapter()
    if thread['platform']=='simulator':return FixtureAdapter() if os.getenv('DATING_AGENT_SOURCE','browser')=='fixture' else BrowserAdapter()
    if thread['platform']=='tinder':
        from agent.tinder import configured, TinderAdapter
        if configured():return TinderAdapter()
        raise UnsupportedPlatform('Tinder is not configured; enable it and provide credentials locally')
    raise UnsupportedPlatform('Unsupported platform')

def telegram_update(update):
    """Webhook inbox transaction: update-ID dedup, trusted business connection, namespaced identities."""
    from datetime import datetime,timezone
    ident=int(update['update_id'])
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('INSERT OR IGNORE INTO updates VALUES(?,?)',(ident,s.utcnow())).rowcount:return
        c=update.get('business_connection')
        if c:
            owner=os.getenv('TELEGRAM_OWNER_ID','')
            if not owner or str(c['user']['id'])!=owner:raise PermissionError('Unrecognized account owner')
            db.execute('INSERT OR REPLACE INTO connections VALUES(?,?,?,?,?)',(c['id'],int(c.get('is_enabled',False)),
                int(c.get('rights',{}).get('can_reply',c.get('can_reply',False))),owner,json.dumps({'date':c.get('date')})))
        deleted=update.get('deleted_business_messages')
        if deleted:
            connection=deleted['business_connection_id'];chat=str(deleted['chat']['id']);thread=f'tg:{connection}:{chat}'
            for mid in deleted.get('message_ids',[]):
                msg=f'{thread}:{mid}'
                db.execute('DELETE FROM source_messages WHERE id=?',(msg,));db.execute('DELETE FROM messages WHERE id=?',(msg,))
                db.execute('DELETE FROM memory WHERE thread_id=? AND source_id=?',(thread,msg))
            db.execute("UPDATE drafts SET status='stale' WHERE thread_id=? AND status='pending'",(thread,))
            db.execute('DELETE FROM outcome_state WHERE thread_id=?',(thread,))
        m=update.get('business_message') or update.get('edited_business_message')
        if m:
            connection=m['business_connection_id'];chat=str(m['chat']['id']);thread=f'tg:{connection}:{chat}'
            con=db.execute('SELECT * FROM connections WHERE id=?',(connection,)).fetchone()
            if not con or not con['enabled']:raise PermissionError('Unknown or disabled business connection')
            if db.execute('SELECT 1 FROM tombstones WHERE thread_id=?',(thread,)).fetchone():return
            if m['chat'].get('type')!='private':return
            sender='you' if str(m.get('from',{}).get('id'))==con['user_id'] or m.get('sender_business_bot') else 'them'
            db.execute('INSERT OR IGNORE INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1)',
                       (thread,m['chat'].get('first_name','Telegram contact'),'telegram',connection,chat))
            if not m.get('text'):
                db.execute('UPDATE threads SET user_paused=1 WHERE id=?',(thread,));return
            msg=f'{thread}:{m["message_id"]}'
            db.execute('INSERT INTO source_messages VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',
                       (msg,thread,sender,m['text'],datetime.fromtimestamp(m['date'],timezone.utc).isoformat()))
            if 'edited_business_message' in update:
                db.execute('DELETE FROM memory WHERE thread_id=? AND source_id=?',(thread,msg))
                db.execute('DELETE FROM messages WHERE id=?',(msg,))
                db.execute('DELETE FROM outcome_state WHERE thread_id=?',(thread,))
                db.execute("UPDATE drafts SET status='stale' WHERE thread_id=? AND status='pending'",(thread,))
