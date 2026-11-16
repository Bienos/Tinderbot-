"""Campaigns: the agent writes the FIRST message to new matches, either sending it or leaving a draft for the owner.

The owner picks the matches and a mode, then presses start:
- auto:  the opener is written and sent by the agent (needs autopilot: plan, AI disclosure, connection) one at a time;
- draft: the opener is written and waits in the conversation for the owner's "Send" click.
A conversation the owner (or she) already started is never touched. Everything a reply must pass still applies:
the independent factual review, global pause, per-thread pause/archive, plan slots, consent/disclosure for automatic
sends, durable send budgets and the uncertain-delivery block. On top of those, automatic openers are spread out
(CAMPAIGN_GAP_SECONDS apart) and leave part of the hourly Tinder budget free for replies. These are service-load and
account-safety choices, not a verified safe rate (see docs/ACCOUNT_RISK.md).
"""
from __future__ import annotations

import time
from uuid import uuid4

from agent import storage as s, runtime as rt, plans
from agent.limits import integer, tinder_sends_since

MODES = ('auto', 'draft')
ACTIVE = ('queued', 'working')


def gap_seconds() -> int:
    """Pause between two automatic openers. Drafts are not sent, so they are not spaced."""
    return integer('CAMPAIGN_GAP_SECONDS', 240, 0, 86400)


def reply_reserve() -> int:
    """Hourly Tinder sends kept free for replies to people who answered: openers never use the last few."""
    return integer('CAMPAIGN_REPLY_RESERVE', 5, 0, 1000)


def daily_cap() -> int:
    return integer('CAMPAIGN_OPENERS_PER_DAY', 30, 1, 1000)


def blocker(thread: dict | None, history: list, *, queued: bool = True) -> str | None:
    """Why a first message cannot be written for this conversation now (None: it can)."""
    if not thread:
        return 'Tego dopasowania już nie ma.'
    if thread.get('platform') not in ('tinder', 'simulator'):
        return 'Pierwszą wiadomość można zaplanować tylko na Tinderze.'
    if not thread.get('source_seen'):
        return 'Tego dopasowania jeszcze nie sprawdzono. Zsynchronizuj i spróbuj ponownie.'
    if history or s.source_for_thread(thread['id']):
        return 'Ta rozmowa już się zaczęła.'
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


def launch(thread_ids: list[str], mode: str) -> dict:
    """Queue first messages for the chosen new matches. Returns who was accepted and, for the rest, why not."""
    if mode not in MODES:
        raise ValueError('mode')
    threads = {t['id']: t for t in s.threads()}
    by_thread = s.messages_by_thread()
    accepted: list[str] = []
    rejected: dict[str, str] = {}
    for tid in dict.fromkeys(thread_ids):
        t = threads.get(tid)
        reason = blocker(t, by_thread.get(tid, []))
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
            db.execute('INSERT INTO campaigns(id,created,mode) VALUES(?,?,?)', (campaign, s.utcnow(), mode))
            for pos, tid in enumerate(accepted):
                db.execute('INSERT OR REPLACE INTO campaign_items(thread_id,campaign_id,mode,status,note,position,available,updated,attempts) '
                           "VALUES(?,?,?,'queued',NULL,?,0,?,0)", (tid, campaign, mode, pos, now))
                # A fresh opener is always written again; one that already has a delivery attempt was refused above.
                db.execute("UPDATE drafts SET status='regenerate' WHERE thread_id=? AND anchor_message_id=? "
                           "AND status IN ('pending','stale','rejected','needs_user','no_reply')", (tid, s.OPENER_ANCHOR))
        for tid in accepted:
            rt.audit(tid, 'campaign_queued', 'Owner asked the agent to write the first message (' + mode + ')')
    return {'campaign_id': campaign, 'mode': mode, 'accepted': accepted, 'rejected': rejected}


def send_room() -> bool:
    """May another opener be SENT now: spaced out, replies keep part of the budget, and a daily cap for openers."""
    now = time.time()
    with s.connect() as db:
        last = db.execute("SELECT MAX(updated) FROM campaign_items WHERE status='sent'").fetchone()[0]
        today = db.execute("SELECT COUNT(*) FROM campaign_items WHERE status='sent' AND updated>?", (now - 86400,)).fetchone()[0]
    if last and now - last < gap_seconds():
        return False
    if today >= daily_cap():
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
    room = None
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT i.* FROM campaign_items i JOIN campaigns c ON c.id=i.campaign_id WHERE i.status='queued' "
                          'AND c.stopped=0 AND i.available<=? ORDER BY c.created, i.position', (time.time(),)).fetchall()
        for r in rows:
            if r['mode'] == 'auto':
                if room is None:
                    room = send_room()
                if not room:
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


def status(history: dict | None = None) -> dict:
    """What the panel shows: capacity, pacing and per-conversation progress."""
    by_thread = history if history is not None else s.messages_by_thread()
    items, counts = {}, {}
    for r in s.rows('SELECT i.*,c.stopped FROM campaign_items i JOIN campaigns c ON c.id=i.campaign_id'):
        st = 'queued' if r['status'] == 'working' else r['status']
        if st == 'review' and by_thread.get(r['thread_id']):
            st = 'started'  # the owner sent it (or she wrote first): nothing is waiting any more
        items[r['thread_id']] = {'status': st, 'note': r['note'], 'mode': r['mode']}
        counts[st] = counts.get(st, 0) + 1
    return {'items': items, 'counts': counts, 'running': counts.get('queued', 0) > 0,
            'gap_seconds': gap_seconds(), 'daily_cap': daily_cap(), 'free_slots': plans.free_slots()}
