"""Campaigns: the agent writes the FIRST message to new matches, either sending it or leaving a draft for the owner.

The owner picks the matches and a mode, then presses start:
- auto:  the opener is written and sent by the agent (needs autopilot: plan, AI disclosure, connection) one at a time;
- draft: the opener is written and waits in the conversation for the owner's "Send" click.
A conversation the owner (or she) already started is never touched. Everything a reply must pass still applies:
the independent factual review, global pause, per-thread pause/archive, plan slots, consent/disclosure for automatic
sends, durable send budgets and the uncertain-delivery block. On top of those, automatic openers follow a pace profile
(careful / balanced / fast: spacing, a daily cap and a sending window in local time) and leave part of the hourly Tinder
budget free for replies. These are service-load and account-safety choices, not a verified safe rate (see
docs/ACCOUNT_RISK.md). CAMPAIGN_GAP_SECONDS, CAMPAIGN_OPENERS_PER_DAY and CAMPAIGN_WINDOW override every profile.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent import storage as s, runtime as rt, plans
from agent.limits import integer, tinder_sends_since

MODES = ('auto', 'draft')
ACTIVE = ('queued', 'working')


PROFILES = {
    'careful': {'label': 'Ostrożny', 'gap': 480, 'per_day': 8, 'window': (18.0, 22.0),
                'hint': 'Najbezpieczniejszy. Dobry na start, na świeże konto albo takie, które mało pisało.'},
    'balanced': {'label': 'Zrównoważony', 'gap': 300, 'per_day': 15, 'window': (17.0, 22.5),
                 'hint': 'Rozsądny na co dzień, gdy konto już pisało wcześniej.'},
    'fast': {'label': 'Szybki', 'gap': 180, 'per_day': 30, 'window': (10.0, 23.0),
             'hint': 'Najszybszy, ale też najbardziej widoczny dla Tindera. Używaj z głową.'},
}
DEFAULT_PROFILE = 'balanced'


def profile_of(name: str | None) -> dict:
    return PROFILES.get(name or DEFAULT_PROFILE) or PROFILES[DEFAULT_PROFILE]


def gap_seconds(profile: str | None = None) -> int:
    """Pause between two automatic openers. Drafts are not sent, so they are not spaced."""
    return integer('CAMPAIGN_GAP_SECONDS', profile_of(profile)['gap'], 0, 86400)


def reply_reserve() -> int:
    """Hourly Tinder sends kept free for replies to people who answered: openers never use the last few."""
    return integer('CAMPAIGN_REPLY_RESERVE', 5, 0, 1000)


def daily_cap(profile: str | None = None) -> int:
    return integer('CAMPAIGN_OPENERS_PER_DAY', profile_of(profile)['per_day'], 1, 1000)


def timezone_name() -> str:
    return os.getenv('AUTOMATION_TZ', '').strip() or 'Europe/Warsaw'


def window_hours(profile: str | None = None) -> tuple[float, float] | None:
    """Local sending window (start, end) in hours, or None for "always". CAMPAIGN_WINDOW="17:00-22:30" or "always" overrides."""
    raw = os.getenv('CAMPAIGN_WINDOW', '').strip().lower()
    if raw == 'always':
        return None
    if raw:
        try:
            a, b = raw.split('-')
            conv = lambda x: int(x.split(':')[0]) + (int(x.split(':')[1]) / 60 if ':' in x else 0)
            return conv(a), conv(b)
        except (ValueError, IndexError):
            pass
    return profile_of(profile)['window']


def in_window(profile: str | None = None, now: float | None = None) -> bool:
    w = window_hours(profile)
    if w is None:
        return True
    try:
        local = datetime.fromtimestamp(now if now is not None else time.time(), ZoneInfo(timezone_name()))
    except Exception:
        return True  # an unknown time zone must not stop everything silently
    hour = local.hour + local.minute / 60
    return w[0] <= hour < w[1] if w[0] <= w[1] else (hour >= w[0] or hour < w[1])


def _clock(h: float) -> str:
    return f'{int(h):02d}:{int(round((h - int(h)) * 60)):02d}'


def bio_of(thread_id: str) -> str:
    rows = s.rows('SELECT value FROM tinder_threads WHERE thread_id=?', (thread_id,))
    try:
        return str(((json.loads(rows[0]['value']) if rows else {}).get('profile') or {}).get('bio') or '').strip()
    except ValueError:
        return ''


def blocker(thread: dict | None, history: list, *, queued: bool = True, need_bio: bool = False) -> str | None:
    """Why a first message cannot be written for this conversation now (None: it can)."""
    if not thread:
        return 'Tego dopasowania już nie ma.'
    if thread.get('platform') not in ('tinder', 'simulator'):
        return 'Pierwszą wiadomość można zaplanować tylko na Tinderze.'
    if not thread.get('source_seen'):
        return 'Tego dopasowania jeszcze nie sprawdzono. Zsynchronizuj i spróbuj ponownie.'
    if history or s.source_for_thread(thread['id']):
        return 'Ta rozmowa już się zaczęła.'
    if need_bio and not bio_of(thread['id']):
        return 'Brak opisu w profilu: otwarcie byłoby ogólne.'
    if thread['user_archived'] or thread['user_paused']:
        return 'Rozmowa jest wstrzymana albo w archiwum.'
    if thread['source_visibility'] != 'available':
        return 'Dopasowanie jest chwilowo niedostępne.'
    if not rt.eligible(thread):
        return 'Agent jest wstrzymany albo połączenie z Tinderem jest wyłączone.'
    if s.rows("SELECT 1 FROM actions WHERE thread_id=? AND status IN ('sending','uncertain')", (thread['id'],)):
        return 'Poprzednia wysyłka nie jest potwierdzona. Sprawdź rozmowę w Tinderze.'
    if s.rows('SELECT 1 FROM actions a JOIN drafts d ON d.id=a.draft_id WHERE d.thread_id=? AND d.anchor_message_id=?',
              (thread['id'], s.OPENER_ANCHOR)):
        return 'Poprzednia próba wysłania nie wyszła. Napisz tę wiadomość sam.'
    if queued and s.rows("SELECT 1 FROM campaign_items i JOIN campaigns c ON c.id=i.campaign_id WHERE i.thread_id=? "
                         "AND i.status IN ('queued','working') AND c.stopped=0", (thread['id'],)):
        return 'Ta rozmowa jest już w kolejce kampanii.'
    return None


def launch(thread_ids: list[str], mode: str, profile: str = DEFAULT_PROFILE, only_with_bio: bool = False) -> dict:
    """Queue first messages for the chosen new matches. Returns who was accepted and, for the rest, why not."""
    if mode not in MODES or profile not in PROFILES:
        raise ValueError('mode')
    threads = {t['id']: t for t in s.threads()}
    by_thread = s.messages_by_thread()
    accepted: list[str] = []
    rejected: dict[str, str] = {}
    for tid in dict.fromkeys(thread_ids):
        t = threads.get(tid)
        reason = blocker(t, by_thread.get(tid, []), need_bio=only_with_bio)
        if not reason and not plans.admit(t):
            _, plan = plans.current()
            reason = f'Brak wolnych miejsc w pakiecie {plan["label"]} ({plans.limit()} aktywnych rozmów).'
        if reason:
            rejected[tid] = reason
        else:
            accepted.append(tid)
    campaign = None
    if accepted:
        campaign = uuid4().hex
        now = time.time()
        with s.connect() as db:
            db.execute('INSERT INTO campaigns(id,created,mode,profile) VALUES(?,?,?,?)', (campaign, s.utcnow(), mode, profile))
            for pos, tid in enumerate(accepted):
                db.execute('INSERT OR REPLACE INTO campaign_items(thread_id,campaign_id,mode,status,note,position,available,updated,attempts) '
                           "VALUES(?,?,?,'queued',NULL,?,0,?,0)", (tid, campaign, mode, pos, now))
                # A fresh opener is always written again; one that already has a delivery attempt was refused above.
                db.execute("UPDATE drafts SET status='regenerate' WHERE thread_id=? AND anchor_message_id=? "
                           "AND status IN ('pending','stale','rejected','needs_user','no_reply')", (tid, s.OPENER_ANCHOR))
        for tid in accepted:
            rt.audit(tid, 'campaign_queued', 'Owner asked the agent to write the first message (' + mode + ')')
    return {'campaign_id': campaign, 'mode': mode, 'profile': profile, 'accepted': accepted, 'rejected': rejected}


def send_room(profile: str | None = None) -> bool:
    """May another opener be SENT now: inside the sending window, spaced out, replies keep part of the budget, and a daily cap."""
    now = time.time()
    if not in_window(profile, now):
        return False
    with s.connect() as db:
        last = db.execute("SELECT MAX(updated) FROM campaign_items WHERE status='sent'").fetchone()[0]
        today = db.execute("SELECT COUNT(*) FROM campaign_items WHERE status='sent' AND updated>?", (now - 86400,)).fetchone()[0]
    if last and now - last < gap_seconds(profile):
        return False
    if today >= daily_cap(profile):
        return False
    if tinder_sends_since(3600) >= integer('TINDER_SENDS_PER_HOUR', 20) - reply_reserve():
        return False
    if tinder_sends_since(86400) >= integer('TINDER_SENDS_PER_DAY', 100) - reply_reserve():
        return False
    return True


def claim_next() -> dict | None:
    """The next queued opener that may run now (marks it 'working'). Automatic ones wait for send_room()."""
    if rt.settings()['paused']:
        return None
    rooms: dict = {}
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT i.*,c.profile FROM campaign_items i JOIN campaigns c ON c.id=i.campaign_id WHERE i.status='queued' "
                          'AND c.stopped=0 AND i.available<=? ORDER BY c.created, i.position', (time.time(),)).fetchall()
        for r in rows:
            if r['mode'] == 'auto':
                if r['profile'] not in rooms:
                    rooms[r['profile']] = send_room(r['profile'])
                if not rooms[r['profile']]:
                    continue
            db.execute("UPDATE campaign_items SET status='working',attempts=attempts+1,updated=? WHERE thread_id=?", (time.time(), r['thread_id']))
            return {**dict(r), 'attempts': r['attempts'] + 1}
    return None


def finish(thread_id: str, status: str, note: str | None = None) -> None:
    with s.connect() as db:
        db.execute('UPDATE campaign_items SET status=?,note=?,updated=? WHERE thread_id=?', (status, note, time.time(), thread_id))
    if status in ('skipped', 'failed'):
        plans.release_if_empty(thread_id)


def requeue(thread_id: str, delay: float, note: str) -> None:
    with s.connect() as db:
        db.execute("UPDATE campaign_items SET status='queued',note=?,available=?,updated=? WHERE thread_id=?",
                   (note, time.time() + delay, time.time(), thread_id))


def stop() -> int:
    """Stop every running campaign. What is already sent stays; drafts left for the owner stay; the rest is dropped."""
    with s.connect() as db:
        db.execute("UPDATE campaigns SET stopped=1 WHERE stopped=0")
        ids = [r['thread_id'] for r in db.execute("SELECT thread_id FROM campaign_items WHERE status IN ('queued','working')").fetchall()]
        db.execute("UPDATE campaign_items SET status='skipped',note='Zatrzymano kampanię.',updated=? WHERE status IN ('queued','working')",
                   (time.time(),))
    for tid in ids:
        plans.release_if_empty(tid)
    if ids:
        rt.audit(None, 'campaign_stopped', f'Owner stopped the campaign; {len(ids)} first messages dropped')
    return len(ids)


DATE_KINDS = {'date_confirmed', 'date_tentative'}


def _person(item: dict, msgs: list, kinds: set) -> str:
    """Where one person is in a round, from what actually happened in the conversation (not from our own bookkeeping)."""
    if kinds & DATE_KINDS:
        return 'date'
    hers = any(m['sender'] == 'them' for m in msgs)
    if hers and len(msgs) >= 5:
        return 'talking'
    if hers:
        return 'replied'
    if any(m['sender'] == 'you' for m in msgs):
        return 'sent'
    return {'working': 'queued'}.get(item['status'], item['status'])


def rounds(by_thread: dict, outcomes: dict | None = None) -> list[dict]:
    """Every run ("runda") with its results, newest first. Results come from the conversations themselves, so a first
    message the owner sent from a draft counts too. (A person re-queued in a later run belongs to that later run.)"""
    outcomes = outcomes or {}
    campaigns_ = s.rows('SELECT * FROM campaigns ORDER BY created, rowid')
    threads = {t['id']: t for t in s.threads()}
    items: dict = {}
    for r in s.rows('SELECT * FROM campaign_items ORDER BY position'):
        items.setdefault(r['campaign_id'], []).append(r)
    out = []
    for n, c in enumerate(campaigns_, 1):
        people = []
        for it in items.get(c['id'], []):
            msgs = by_thread.get(it['thread_id'], [])
            people.append({'thread_id': it['thread_id'], 'name': (threads.get(it['thread_id']) or {}).get('display_name', '?'),
                           'status': _person(it, msgs, set(outcomes.get(it['thread_id'], []))), 'note': it['note'], 'messages': len(msgs)})
        count = lambda *k: sum(1 for x in people if x['status'] in k)
        queued = count('queued')
        out.append({'id': c['id'], 'number': n, 'name': f'Runda #{n}', 'created': c['created'], 'mode': c['mode'], 'profile': c['profile'],
                    'status': 'stopped' if c['stopped'] else 'active' if queued else 'done',
                    'total': len(people), 'queued': queued, 'sent': count('sent', 'replied', 'talking', 'date'),
                    'replied': count('replied', 'talking', 'date'), 'talking': count('talking', 'date'), 'dates': count('date'),
                    'people': people})
    return [r for r in reversed(out) if r['total']]


def status(history: dict | None = None, outcomes: dict | None = None) -> dict:
    """What the panel shows: capacity, pacing and per-conversation progress."""
    by_thread = history if history is not None else s.messages_by_thread()
    items, counts = {}, {}
    for r in s.rows('SELECT i.*,c.stopped FROM campaign_items i JOIN campaigns c ON c.id=i.campaign_id'):
        st = 'queued' if r['status'] == 'working' else r['status']
        if st == 'review' and by_thread.get(r['thread_id']):
            st = 'started'  # the owner sent it (or she wrote first): nothing is waiting any more
        items[r['thread_id']] = {'status': st, 'note': r['note'], 'mode': r['mode']}
        counts[st] = counts.get(st, 0) + 1
    profiles = {}
    for key, v in PROFILES.items():
        w = window_hours(key)
        profiles[key] = {'label': v['label'], 'hint': v['hint'], 'gap_seconds': gap_seconds(key), 'per_day': daily_cap(key),
                         'window': [_clock(w[0]), _clock(w[1])] if w else None}
    return {'items': items, 'counts': counts, 'rounds': rounds(by_thread, outcomes), 'running': counts.get('queued', 0) > 0,
            'gap_seconds': gap_seconds(), 'daily_cap': daily_cap(), 'free_slots': plans.free_slots(),
            'profiles': profiles, 'default_profile': DEFAULT_PROFILE, 'reserve': reply_reserve(), 'timezone': timezone_name()}
