"""Unofficial Tinder adapter, adapted from OpenDate (MIT), pinned in THIRD_PARTY_NOTICES.md.

Read-only retries are bounded. Message POSTs execute once; receipts require read-back.
No swiping, login extraction, stealth headers, CAPTCHA handling or private-token logging.
"""
from __future__ import annotations
import asyncio
import hashlib
import uuid
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import httpx
from urllib.parse import urlsplit
from agent import storage as s, runtime as rt
from agent import tinder_traffic as traffic

BASE_URL = 'https://api.gotinder.com'
ID = re.compile(r'^[A-Za-z0-9_-]{1,160}$')

class TinderError(Exception):
    """Only controlled, nonsecret error codes are allowed in exception messages."""
class TinderAuthError(TinderError): pass
class TinderRestriction(TinderAuthError): pass
class TinderProtocolError(TinderError): pass
class TinderRejected(TinderError): pass
class TinderUnavailable(TinderError): pass
class TinderUncertain(TinderError): pass
class TinderRateLimited(TinderError):
    def __init__(self, delay=60):
        self.delay = max(15, delay)
        self.existing=False
        self.reason='rate_limited'
        super().__init__('rate_limited')

def active_cooldown(delay):
    limited=TinderRateLimited(delay);limited.existing=True;limited.reason='cooldown_active'
    return limited

@dataclass(frozen=True)
class Page:
    items: list[dict]
    complete: bool


def ident(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise TinderProtocolError('invalid_source_identity')
    return value


def timestamp(value: Any) -> str:
    if not isinstance(value, str): raise TinderProtocolError('missing_message_timestamp')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None: raise ValueError()
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        raise TinderProtocolError('invalid_message_timestamp') from None



def _iso(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None


def _tinder_https(url):
    if not isinstance(url, str) or len(url) > 500: return False
    parts = urlsplit(url); host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and (host == 'gotinder.com' or host.endswith('.gotinder.com'))


def profile_summary(person: dict, match: dict | None = None) -> dict:
    """Display-only profile data for the owner's dashboard: image links (Tinder hosts only), bio, age, timestamps."""
    photos, full = [], []
    for ph in (person.get('photos') or [])[:9]:
        if not isinstance(ph, dict): continue
        files = [f for f in (ph.get('processedFiles') or []) if isinstance(f, dict) and _tinder_https(f.get('url'))]
        # Prefer the smallest rendition that is still sharp enough for a card (>=320px wide); else the largest.
        big = sorted((f for f in files if isinstance(f.get('width'), int) and f['width'] >= 320), key=lambda f: f['width'])
        url = big[0]['url'] if big else (max(files, key=lambda f: f.get('width') or 0)['url'] if files else None)
        if not url and _tinder_https(ph.get('url')): url = ph['url']
        if url:
            # Full-size version for the photo viewer: the original, else the widest rendition.
            largest = max(files, key=lambda f: f.get('width') or 0)['url'] if files else None
            photos.append(url); full.append(ph['url'] if _tinder_https(ph.get('url')) else (largest or url))
    bio = person.get('bio'); age = None
    try:
        born = datetime.fromisoformat(str(person.get('birth_date')).replace('Z', '+00:00'))
        today = datetime.now(timezone.utc); age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if not 18 <= age <= 120: age = None
    except ValueError: age = None
    match = match or {}
    return {'photos': photos, 'photos_full': full, 'bio': bio.strip()[:600] if isinstance(bio, str) else '', 'age': age,
            'matched_at': _iso(match.get('created_date')), 'last_activity': _iso(match.get('last_activity_date'))}


TOKEN_SLOT = 'tinder_token'


def valid_token_format(value: str) -> bool:
    return bool(value) and 8 <= len(value) <= 4096 and all(33 <= ord(c) <= 126 for c in value)


def token_source() -> str | None:
    from agent import vault
    if vault.has(TOKEN_SLOT): return 'vault'
    return 'env' if os.getenv('TINDER_AUTH_TOKEN', '').strip() else None


def token() -> str:
    # A token saved by the customer in their own dashboard (encrypted) wins over the operator env variable.
    from agent import vault
    value = (vault.get(TOKEN_SLOT) or '') if vault.has(TOKEN_SLOT) else os.getenv('TINDER_AUTH_TOKEN', '').strip()
    if not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise TinderAuthError('tinder_token_missing_or_invalid')
    return value


def fingerprint() -> str:
    return hashlib.sha256(token().encode()).hexdigest()


def configured() -> bool:
    return os.getenv('TINDER_ENABLED', 'false').lower() == 'true' and token_source() is not None


def poll_interval() -> int:
    try: return max(60, min(3600, int(os.getenv('TINDER_POLL_INTERVAL', '180'))))
    except ValueError: return 180


class TinderClient:
    """OpenDate-derived async HTTP connector, without its mutation retry/synthetic receipt paths."""
    def __init__(self, auth_token: str, *, transport=None, max_pages: int = 20):
        self.max_pages = max(1, max_pages)
        self.credential_hash=hashlib.sha256(auth_token.encode()).hexdigest()
        self.reconnect=False
        self.client = httpx.AsyncClient(
            base_url=BASE_URL, timeout=10, transport=transport, follow_redirects=False, trust_env=False,
            headers={'X-Auth-Token': auth_token, 'Accept': 'application/json',
                     'User-Agent': 'ConversationAgent/1.0 (OpenDate-derived)',
                     # Tinder's v2 inbox rejects bare requests (HTTP 401). These are the plain
                     # client-identification headers; override via env when Tinder bumps versions.
                     'platform': 'web', 'Accept-Language': os.getenv('TINDER_LOCALE', 'en-GB'),
                     'app-version': os.getenv('TINDER_APP_VERSION', '1074202'),
                     'tinder-version': os.getenv('TINDER_VERSION', '7.42.2'),
                     'persistent-device-id': os.getenv('TINDER_DEVICE_ID') or str(uuid.uuid5(uuid.NAMESPACE_URL, 'conversation-agent:' + self.credential_hash))})

    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self.client.aclose()

    def pause_account(self,reason):
        for row in s.rows("SELECT * FROM connections WHERE id LIKE 'tinder:%' AND enabled=1"):
            state=json.loads(row['value'])
            if state.get('credential_fingerprint')==self.credential_hash:
                status_update(row['id'],error=reason,disable=True)

    def restriction(self,reason):
        self.pause_account('restriction_requires_manual_review')
        raise TinderRestriction(reason)

    async def request(self, method: str, path: str, **kwargs) -> dict:
        # Only exact-host relative paths constructed by this module are accepted.
        if not path.startswith('/') or path.startswith('//') or '://' in path:
            raise TinderProtocolError('invalid_request_path')
        attempts = 3 if method == 'GET' else 1
        for attempt in range(attempts):
            # Respect account cooldowns even for explicit reconnect attempts and read retries.
            for row in s.rows("SELECT * FROM connections WHERE id LIKE 'tinder:%'"):
                state=json.loads(row['value'])
                if state.get('credential_fingerprint')!=self.credential_hash:continue
                if state.get('blocked_until',0)>time.time():raise active_cooldown(state['blocked_until']-time.time())
                if not row['enabled'] and not self.reconnect:raise TinderAuthError('connection_paused')
            try:traffic.claim_request()
            except traffic.TrafficBudget as exc:
                limited=TinderRateLimited(exc.delay);limited.reason='local_request_budget';raise limited from None
            try:
                async with self.client.stream(method,path,**kwargs) as stream:
                    chunks=bytearray()
                    async for chunk in stream.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks)>4*1024*1024:raise TinderProtocolError('source_response_too_large')
                    # aiter_bytes already decodes Content-Encoding. Reusing those
                    # headers would make Response decode the plaintext a second time.
                    decoded_headers=stream.headers.copy()
                    for header in ('Content-Encoding','Content-Length','Transfer-Encoding'):
                        decoded_headers.pop(header,None)
                    response=httpx.Response(stream.status_code,headers=decoded_headers,content=bytes(chunks),request=stream.request)
            except httpx.DecodingError:
                if method!='GET':raise TinderUncertain('send_receipt_invalid') from None
                raise TinderProtocolError('invalid_source_encoding') from None
            except httpx.TransportError:
                if method != 'GET': raise TinderUncertain('send_delivery_unknown') from None
                if attempt + 1 == attempts: raise TinderUnavailable('read_transport_failed') from None
                await asyncio.sleep(2 ** attempt); continue
            if response.status_code in (403,423,451):self.restriction('account_restriction_requires_review')
            if response.status_code==401:
                reason='inbox_access_denied' if path.startswith('/v2/matches') else 'session_expired_or_access_denied'
                self.pause_account(reason)
                raise TinderAuthError(reason)
            if response.status_code == 429:
                try:delay=traffic.retry_after(response.headers.get('Retry-After'))
                except OverflowError:self.restriction('cooldown_requires_manual_review')
                raise TinderRateLimited(delay)
            if response.status_code == 404: raise TinderUnavailable('source_not_observed')
            if 500 <= response.status_code:
                if response.headers.get('Retry-After'):
                    try:delay=traffic.retry_after(response.headers['Retry-After'])
                    except OverflowError:self.restriction('cooldown_requires_manual_review')
                    if method!='GET':
                        for row in s.rows("SELECT * FROM connections WHERE id LIKE 'tinder:%' AND enabled=1"):
                            state=json.loads(row['value'])
                            if state.get('credential_fingerprint')==self.credential_hash:status_update(row['id'],error='server_retry_after',delay=delay)
                        raise TinderUncertain('send_server_result_unknown')
                    limited=TinderRateLimited(delay);limited.reason='server_retry_after';raise limited
                if method != 'GET': raise TinderUncertain('send_server_result_unknown')
                if attempt + 1 == attempts: raise TinderUnavailable('source_server_error')
                await asyncio.sleep(2 ** attempt); continue
            if 300 <= response.status_code < 400: self.restriction('redirect_requires_review')
            if not 200 <= response.status_code < 300: raise TinderRejected('request_rejected')
            content_type=response.headers.get('Content-Type','').lower()
            if 'text/html' in content_type and any(word in response.text[:4096].lower() for word in ('captcha','verify you are human','account suspended','challenge')):
                self.restriction('verification_requires_manual_review')
            try: data = response.json()
            except ValueError:
                if method != 'GET': raise TinderUncertain('send_receipt_invalid') from None
                raise TinderProtocolError('invalid_source_json') from None
            if not isinstance(data, dict): raise TinderProtocolError('unexpected_source_shape')
            # Only top-level service status markers are examined, never partner message text.
            if data.get('requires_verification') is True or data.get('captcha') or data.get('challenge'):
                self.restriction('verification_requires_manual_review')
            return data
        raise TinderUnavailable('read_failed')

    async def profile(self) -> str:
        data = await self.request('GET', '/profile')
        root = data.get('data', data)
        if not isinstance(root, dict): raise TinderProtocolError('invalid_profile')
        user = root.get('user', root)
        if not isinstance(user, dict): raise TinderProtocolError('invalid_profile')
        return ident(user.get('_id') or user.get('id'))

    async def pages(self, path: str, key: str, count: int, extra: dict | None = None) -> Page:
        collected = {}; cursor = None; seen = set()
        for _ in range(self.max_pages):
            params = {'count': count, **(extra or {})}
            if cursor: params['page_token'] = cursor
            data = await self.request('GET', path, params=params)
            block = data.get('data')
            if not isinstance(block, dict) or not isinstance(block.get(key), list):
                raise TinderProtocolError('invalid_paginated_response')
            for raw in block[key]:
                if not isinstance(raw, dict): raise TinderProtocolError('invalid_source_record')
                rid = ident(raw.get('_id') or raw.get('id'))
                if rid in collected and collected[rid] != raw: raise TinderProtocolError('conflicting_duplicate_record')
                collected[rid] = raw
            cursor = block.get('next_page_token')
            if not cursor: return Page(list(collected.values()), True)
            if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in seen:
                raise TinderProtocolError('invalid_pagination_cursor')
            seen.add(cursor)
        return Page(list(collected.values()), False)

    async def matches(self) -> Page:
        # Tinder's web app lists new matches (message=0) and conversations (message=1) separately.
        merged = {}; complete = True
        for flag in (0, 1):
            try: page = await self.pages('/v2/matches', 'matches', 60, extra={'message': flag, 'is_tinder_u': 'false', 'locale': 'en-GB'})
            except TinderRejected:
                if flag == 0: raise
                continue
            complete = complete and page.complete
            for m in page.items: merged.setdefault(ident(m.get('_id') or m.get('id')), m)
        return Page(list(merged.values()), complete)

    async def check_inbox_access(self):
        # Verify one page without importing chats or enabling any operation.
        data=await self.request('GET','/v2/matches',params={'count':60})
        block=data.get('data')
        if not isinstance(block,dict) or not isinstance(block.get('matches'),list):
            raise TinderProtocolError('invalid_paginated_response')

    async def messages(self, match_id: str, owner_id: str, person_id: str, thread_id: str) -> Page:
        page = await self.pages(f'/v2/matches/{ident(match_id)}/messages', 'messages', 100)
        items = []
        for raw in page.items:
            if raw.get('match_id') is not None and raw['match_id'] != match_id:
                raise TinderProtocolError('message_conversation_mismatch')
            sender = raw.get('from')
            if sender not in (owner_id, person_id): raise TinderProtocolError('unknown_message_sender')
            other = person_id if sender == owner_id else owner_id
            if raw.get('to') is not None and raw['to'] != other:
                raise TinderProtocolError('message_recipient_mismatch')
            text = raw.get('message')
            if not isinstance(text, str) or not text.strip() or len(text)>8000: raise TinderProtocolError('unsupported_message_content')
            items.append({'id': f'{thread_id}:{ident(raw.get("_id") or raw.get("id"))}',
                          'thread_id': thread_id, 'sender': 'you' if sender == owner_id else 'them',
                          'body': text, 'created_at': timestamp(raw.get('sent_date') or raw.get('created_date'))})
        # Preserve source newest-first tie ordering when normalizing to chronological order.
        items.reverse(); items.sort(key=lambda m: m['created_at'])
        return Page(items, page.complete)

    async def send_once(self, match_id: str, text: str) -> dict:
        data = await self.request('POST', f'/user/matches/{ident(match_id)}', json={'message': text})
        result = data.get('data', data)
        if not isinstance(result, dict): raise TinderUncertain('send_receipt_missing')
        try: ident(result.get('_id') or result.get('id'))
        except TinderProtocolError: raise TinderUncertain('send_receipt_missing') from None
        return result


def client() -> TinderClient:
    """One injection point for offline contract tests; production host is never configurable."""
    return TinderClient(token())


def connection(connection_id: str) -> tuple[dict, dict]:
    rows = s.rows('SELECT * FROM connections WHERE id=?', (connection_id,))
    if not rows or not rows[0]['id'].startswith('tinder:'): raise TinderAuthError('tinder_connection_missing')
    row = rows[0]; value = json.loads(row['value'])
    if not configured() or not row['enabled'] or value.get('credential_fingerprint') != fingerprint():
        raise TinderAuthError('tinder_connection_disabled_or_credential_changed')
    if value.get('blocked_until', 0) > time.time(): raise active_cooldown(value['blocked_until'] - time.time())
    return row, value


def status_update(connection_id: str, *, error=None, delay=0, disable=False, polled=False):
    with s.connect() as db:
        row = db.execute('SELECT value,enabled FROM connections WHERE id=?', (connection_id,)).fetchone()
        if not row: return
        value = json.loads(row['value']); value['error'] = error
        if error=='rate_limited':
            events=[t for t in value.get('rate_limit_events',[]) if t>time.time()-86400]+[time.time()]
            value['rate_limit_events']=events[-3:]
            delay=max(delay,300*(2**min(len(events)-1,6)))
            if len(events)>=3:disable=True;value['error']='repeated_rate_limits_requires_review'
        value['next_poll'] = time.time() + delay
        if error in ('rate_limited','local_request_budget','server_retry_after'):value['blocked_until']=max(value.get('blocked_until',0),time.time()+delay)
        if polled:
            value['last_sync'] = s.utcnow();value['failures']=0
        elif error and error not in ('rate_limited','local_request_budget'):
            value['failures']=value.get('failures',0)+1
            if value['failures']>=3: disable=True;value['error']='circuit_open_requires_review'
        db.execute('UPDATE connections SET value=?,enabled=CASE WHEN ? THEN 0 ELSE enabled END WHERE id=?',
                   (json.dumps(value), int(disable), connection_id))
        paused_now=disable and bool(row['enabled'])
        reason=value.get('error') or 'account_review_required'
    if paused_now:rt.audit(None,'tinder_connection_paused',reason)


async def connect() -> str:
    if not configured(): raise TinderAuthError('set_tinder_enabled_and_token_locally')
    expected = os.getenv('TINDER_OWNER_ID', '').strip()
    async with client() as api:
        api.reconnect=True
        owner = await api.profile()
        if expected and owner != expected: raise TinderAuthError('account_identity_mismatch')
        await api.check_inbox_access()
    cid = f'tinder:{owner}'
    value = {'platform': 'tinder', 'unofficial': True, 'credential_fingerprint': fingerprint(),
             'error': None, 'last_sync': None, 'next_poll': 0, 'blocked_until': 0,
             'auto_send': True, 'owner_attested': True}
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Reconnecting must never silently restore revoked thread grants or another account.
        db.execute("UPDATE connections SET enabled=0 WHERE id LIKE 'tinder:%'")
        db.execute('INSERT OR REPLACE INTO connections VALUES(?,?,?,?,?)', (cid, 1, 1, owner, json.dumps(value)))
    rt.audit(None, 'tinder_connected', 'Unofficial account connected; automatic sending enabled for consented threads')
    return cid


def replace_history(thread_id: str, items: list[dict]):
    """Reconcile only a complete source snapshot, including edits and removed message content."""
    old = s.source_for_thread(thread_id)
    if rt.history_hash(old) == rt.history_hash(items): return
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM source_messages WHERE thread_id=?', (thread_id,))
        db.execute('DELETE FROM messages WHERE thread_id=?', (thread_id,))
        db.execute('DELETE FROM memory WHERE thread_id=?', (thread_id,))
        db.execute('DELETE FROM outcome_state WHERE thread_id=?', (thread_id,))
        for m in items:
            db.execute('INSERT INTO source_messages VALUES(?,?,?,?,?)',
                       (m['id'], thread_id, m['sender'], m['body'], m['created_at']))


async def _history(api: TinderClient, thread: dict, owner: str) -> list[dict]:
    con, _ = connection(thread['connection_id'])
    value = s.rows('SELECT value FROM tinder_threads WHERE thread_id=?', (thread['id'],))
    if not value or con['user_id'] != owner: raise TinderAuthError('account_identity_mismatch')
    person = json.loads(value[0]['value'])['person_id']
    page = await api.messages(thread['chat_id'], owner, person, thread['id'])
    if not page.complete: raise TinderProtocolError('incomplete_message_history')
    replace_history(thread['id'], page.items)
    return page.items


MISSES_BEFORE_HIDDEN = 3


def _tinder_value(tid: str) -> dict:
    rows = s.rows('SELECT value FROM tinder_threads WHERE thread_id=?', (tid,))
    return json.loads(rows[0]['value']) if rows else {}


def _save_tinder_value(tid: str, value: dict) -> None:
    with s.connect() as db:
        db.execute('INSERT OR REPLACE INTO tinder_threads VALUES(?,?)', (tid, json.dumps(value)))


def _mark_read_failed(tid: str) -> None:
    _save_tinder_value(tid, {**_tinder_value(tid), 'read_failed': True})


def _bump_missed(tid: str) -> int:
    value = _tinder_value(tid)
    value['missed'] = int(value.get('missed', 0)) + 1
    _save_tinder_value(tid, value)
    return value['missed']


async def sync_connection(connection_id: str):
    con, prior_state = connection(connection_id)
    changed=False
    from agent.service import ingest
    async with client() as api:
        owner = await api.profile()
        if owner != con['user_id']: raise TinderAuthError('account_identity_mismatch')
        page = await api.matches(); observed = set()
        listing_signature=hashlib.sha256(json.dumps([(m.get('_id') or m.get('id'),traffic.metadata_key(m)) for m in page.items],sort_keys=True).encode()).hexdigest()
        changed=prior_state.get('listing_signature')!=listing_signature
        for match in page.items:
            # Check account revocation after each network await, before retaining data.
            connection(connection_id)
            match_id = ident(match.get('_id') or match.get('id')); person = match.get('person')
            if not isinstance(person, dict): raise TinderProtocolError('invalid_match_person')
            person_id = ident(person.get('_id') or person.get('id'))
            tid = f'tinder:{owner}:{match_id}'; observed.add(tid)
            if s.rows('SELECT 1 FROM tombstones WHERE thread_id=?', (tid,)): continue
            saved=s.rows('SELECT value FROM tinder_threads WHERE thread_id=?',(tid,))
            cached=json.loads(saved[0]['value']) if saved else {}
            cached={**cached,'profile':profile_summary(person,match)}
            activity_key=traffic.metadata_key(match)
            with s.connect() as db:
                db.execute('INSERT INTO threads(id,display_name,platform,connection_id,chat_id,source_seen) VALUES(?,?,?,?,?,1) '
                           'ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name',
                           (tid, str(person.get('name') or 'Tinder contact')[:100], 'tinder', connection_id, match_id))
                db.execute('INSERT OR REPLACE INTO tinder_threads VALUES(?,?)', (tid, json.dumps({**{k:v for k,v in cached.items() if k!='missed'},'person_id':person_id})))
            if not cached.get('read_failed'):
                # Listed by Tinder again: it is there. A one-off gap in an earlier listing must not hide it for good.
                s.set_thread_flags(tid, visibility='available')
            thread = next(t for t in s.threads() if t['id'] == tid)
            if not traffic.should_read(thread,cached,activity_key):continue
            previous_hash=rt.history_hash(s.source_for_thread(tid))
            try:
                history = await _history(api, thread, owner)
                changed=changed or previous_hash!=rt.history_hash(history)
                s.set_thread_flags(tid, visibility='available')
                thread['source_visibility'] = 'available'; ingest(thread, history)
                ok={k:v for k,v in cached.items() if k not in ('read_failed','missed')}
                with s.connect() as db:db.execute('UPDATE tinder_threads SET value=? WHERE thread_id=?',(json.dumps({**ok,'person_id':person_id,'activity_key':activity_key,'last_read':time.time()}),tid))
            except TinderProtocolError:
                _mark_read_failed(tid)
                s.set_thread_flags(tid, visibility='not_observed')
                rt.audit(tid, 'tinder_thread_needs_review', 'Incomplete, unsupported or ambiguous message data; no send')
            except TinderUnavailable:
                _mark_read_failed(tid)
                s.set_thread_flags(tid, visibility='not_observed')
        if page.complete:
            for thread in s.threads():
                if thread['connection_id'] == connection_id and thread['id'] not in observed:
                    # Hide only after several complete listings in a row without it (unmatch), not after one gap.
                    if _bump_missed(thread['id']) >= MISSES_BEFORE_HIDDEN:
                        s.set_thread_flags(thread['id'], visibility='not_observed')
    idle_rounds=0 if changed else prior_state.get('idle_rounds',0)+1
    delay=min(poll_interval()*(2**min(idle_rounds,5)),max(poll_interval(),traffic.integer('TINDER_IDLE_POLL_INTERVAL',900,60,86400)))
    with s.connect() as db:
        row=db.execute('SELECT value FROM connections WHERE id=?',(connection_id,)).fetchone();value=json.loads(row['value'])
        value.update({'idle_rounds':idle_rounds,'listing_signature':listing_signature})
        if page.complete and not value.get('initial_import_done'):
            value['initial_import_done']=True  # from now on the everyday (lower) request budget applies
            rt.audit(None,'tinder_initial_import_done','First full import finished; switching to everyday request limits')
        db.execute('UPDATE connections SET value=? WHERE id=?',(json.dumps(value),connection_id))
    status_update(connection_id, delay=delay, polled=True)


def clear_local_budget_block():
    """Local request-budget pauses are our own limit, not Tinder's: allow an owner-requested sync to proceed."""
    for row in s.rows("SELECT * FROM connections WHERE id LIKE 'tinder:%' AND enabled=1"):
        value = json.loads(row['value'])
        if value.get('error') in ('local_request_budget', None, 'source_sync_failed'):
            value['blocked_until'] = 0 if value.get('error') == 'local_request_budget' else value.get('blocked_until', 0)
            value['next_poll'] = 0
        value['initial_import_done'] = False  # owner asked for a full re-import: allow the import budget once more
        with s.connect() as db: db.execute('UPDATE connections SET value=? WHERE id=?', (json.dumps(value), row['id']))

async def poll():
    if not configured() or rt.settings()['paused']: return
    for row in s.rows("SELECT * FROM connections WHERE id LIKE 'tinder:%' AND enabled=1"):
        value = json.loads(row['value'])
        if max(value.get('next_poll', 0), value.get('blocked_until', 0)) > time.time(): continue
        try: await sync_connection(row['id'])
        except TinderRateLimited as exc:
            if not exc.existing:status_update(row['id'],error=exc.reason,delay=exc.delay)
        except TinderRestriction:status_update(row['id'],error='restriction_requires_manual_review',disable=True)
        except TinderAuthError as exc: status_update(row['id'], error='inbox_access_denied' if str(exc)=='inbox_access_denied' else 'session_expired_or_account_changed', disable=True)
        except TinderError: status_update(row['id'], error='source_sync_failed', delay=poll_interval())
        except Exception: status_update(row['id'], error='unexpected_sync_failure', delay=poll_interval())


class TinderAdapter:
    async def snapshot(self, thread):
        try:
            con, _ = connection(thread['connection_id'])
            async with client() as api:
                owner = await api.profile()
                if owner != con['user_id']: raise TinderAuthError('account_identity_mismatch')
                return await _history(api, thread, owner)
        except TinderRestriction:
            status_update(thread['connection_id'],error='restriction_requires_manual_review',disable=True)
            raise
        except TinderAuthError as exc:
            status_update(thread['connection_id'],error='inbox_access_denied' if str(exc)=='inbox_access_denied' else 'session_expired_or_account_changed',disable=True)
            raise
        except TinderRateLimited as exc:
            if not exc.existing:status_update(thread['connection_id'],error=exc.reason,delay=exc.delay)
            raise

    async def reconcile(self, thread, action_id):
        # Without a concrete provider receipt, text matching cannot establish delivery identity.
        rows = s.rows('SELECT * FROM tinder_receipts WHERE action_id=? AND thread_id=?', (action_id, thread['id']))
        if not rows or rows[0]['next_check']>time.time(): return None
        with s.connect() as db:db.execute('UPDATE tinder_receipts SET next_check=? WHERE action_id=?',(time.time()+poll_interval(),action_id))
        try: fresh = await self.snapshot(thread)
        except TinderError: return None
        row = rows[0]
        draft = s.rows('SELECT d.body FROM drafts d JOIN actions a ON a.draft_id=d.id WHERE a.id=?', (action_id,))
        if not draft: return None
        for m in fresh:
            if m['id'] == row['message_id'] and m['sender'] == 'you' and m['body'] == draft[0]['body']:
                return m['id']
        return None

    async def send(self, thread, text, action_id, anchor):
        from agent.adapters import StaleAction
        from agent.service import ingest
        reserved = s.rows('SELECT a.*,d.body,c.history_hash,c.settings_hash FROM actions a JOIN drafts d ON d.id=a.draft_id '
                          'JOIN draft_context c ON c.draft_id=d.id WHERE a.id=? AND a.thread_id=?', (action_id, thread['id']))
        if not reserved or reserved[0]['status'] != 'sending' or reserved[0]['body'] != text:
            raise StaleAction('Unreserved Tinder action')
        action = reserved[0]
        con, _ = connection(thread['connection_id'])
        async with client() as api:
            owner = await api.profile()
            if owner != con['user_id']: raise TinderAuthError('account_identity_mismatch')
            fresh = await _history(api, thread, owner)
            ingest(thread, fresh)
            if not fresh or fresh[-1]['id'] != anchor or rt.history_hash(fresh) != action['history_hash']:
                raise StaleAction('New or edited Tinder message invalidates draft')
            # Navigation/network awaits can allow pause, mode changes, grant revocation or deletion.
            current = next((t for t in s.threads() if t['id'] == thread['id']), None)
            grants = s.rows('SELECT * FROM grants WHERE thread_id=?', (thread['id'],))
            connection(thread['connection_id'])
            if not current or not rt.eligible(current) or rt.settings_hash() != action['settings_hash']:
                raise StaleAction('Conversation, account or profile permission changed')
            # Owner-approved sends need no grant; automatic sends need consent and disclosure, checked again here.
            if action['automatic'] and (not grants or not all(grants[0][k] for k in ('enabled', 'participant_consent', 'disclosed'))):
                raise StaleAction('Thread consent or disclosure revoked')
            if action['automatic'] and not rt.auto_allowed(current): raise StaleAction('Automatic sending paused')
            from agent.dispatch import guard
            guard(thread['id'],action_id,text,anchor,fresh)
            try:
                result = await api.send_once(thread['chat_id'], text)
            except TinderRestriction:
                status_update(thread['connection_id'],error='restriction_requires_manual_review',disable=True)
                raise TinderUncertain('restriction_delivery_unverified') from None
            except TinderAuthError:
                status_update(thread['connection_id'], error='session_expired_or_access_denied', disable=True)
                raise TinderRejected('session_expired_or_access_denied') from None
            except TinderRateLimited as exc:
                if not exc.existing:status_update(thread['connection_id'],error=exc.reason,delay=exc.delay)
                raise TinderRejected(exc.reason) from None
            mid = f'{thread["id"]}:{ident(result.get("_id") or result.get("id"))}'
            if any(m['id']==mid for m in fresh):raise TinderUncertain('send_receipt_reuses_existing_message')
            # Persist candidate BEFORE read-back, to allow recovery after a verifier crash.
            with s.connect() as db: db.execute('INSERT INTO tinder_receipts(action_id,thread_id,message_id) VALUES(?,?,?)', (action_id, thread['id'], mid))
            verified = await _history(api, thread, owner)
            ingest(thread,verified)
            for m in verified:
                if m['id'] == mid and m['sender'] == 'you' and m['body'] == text:
                    with s.connect() as db:
                        row=db.execute('SELECT value FROM connections WHERE id=?',(thread['connection_id'],)).fetchone();value=json.loads(row['value'])
                        value.update({'idle_rounds':0,'next_poll':time.time()+poll_interval()})
                        db.execute('UPDATE connections SET value=? WHERE id=?',(json.dumps(value),thread['connection_id']))
                    return mid
            raise TinderUncertain('send_not_yet_observed')


def public_status():
    connections = []
    for row in s.rows("SELECT * FROM connections WHERE id LIKE 'tinder:%'"):
        value = json.loads(row['value'])
        connections.append({'id': row['id'], 'enabled': bool(row['enabled']), 'unofficial': True,
                            'auto_send': bool(value.get('auto_send',False)),
                            'error': value.get('error'), 'last_sync': value.get('last_sync'),
                            'next_poll': value.get('next_poll', 0), 'blocked_until':value.get('blocked_until',0), 'failures':value.get('failures',0)})
    from agent import vault
    tail = None
    if token_source():
        try: tail = fingerprint()[-6:]
        except TinderAuthError: tail = None
    return {'configured': configured(), 'enabled': os.getenv('TINDER_ENABLED', 'false').lower() == 'true',
            'unofficial': True, 'connections': connections, 'token_source': token_source(),
            'token_fingerprint': tail, 'vault_ready': vault.available()}
