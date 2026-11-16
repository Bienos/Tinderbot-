"""Plans (pakiety): how many conversations the agent actively handles, and whether it may answer on its own.

PLAN on a customer's bot picks the plan (winq, flirt, casanova). Without PLAN (the owner's own bot, old
installations) nothing is limited. PLAN_CONVERSATIONS overrides the number of active conversations.

A conversation takes a slot when the other person writes to it and a slot is free. It keeps the slot until it goes cold
(no message for ACTIVE_DAYS), is archived or paused, or is deleted. Conversations that reached the date stage always get
a slot and are never blocked: that is the moment the customer pays for. Conversations without a slot wait in a queue:
nothing is drafted for them, and they are admitted as soon as a slot frees up. Safety budgets against Tinder blocks
(agent/limits.py) are the same in every plan.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from agent import storage as s

PLANS = {
    'winq': {'label': 'Winq', 'conversations': 3, 'autopilot': False, 'advanced_stats': False},
    'flirt': {'label': 'Flirt', 'conversations': 10, 'autopilot': True, 'advanced_stats': False},
    'casanova': {'label': 'Casanova', 'conversations': 30, 'autopilot': True, 'advanced_stats': True},
}
ACTIVE_DAYS = 14
DATE_KINDS = {'date_suggested', 'date_tentative', 'date_confirmed'}


def current() -> tuple[str | None, dict | None]:
    name = os.getenv('PLAN', '').strip().lower()
    return (name, PLANS[name]) if name in PLANS else (None, None)


def limited() -> bool:
    return current()[1] is not None


def limit() -> int | None:
    _, plan = current()
    if not plan:
        return None
    try:
        return max(1, int(os.getenv('PLAN_CONVERSATIONS', '') or plan['conversations']))
    except ValueError:
        return plan['conversations']


def autopilot_allowed() -> bool:
    _, plan = current()
    return True if plan is None else plan['autopilot']


def ensure(db) -> None:
    db.execute('CREATE TABLE IF NOT EXISTS plan_slots (thread_id TEXT PRIMARY KEY, admitted TEXT NOT NULL)')


def _recent(ts: str | None) -> bool:
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except ValueError:
        return True  # an unreadable date must not push a conversation out
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when >= datetime.now(timezone.utc) - timedelta(days=ACTIVE_DAYS)


def _date_stage(db, thread_id: str) -> bool:
    row = db.execute('SELECT value FROM outcome_state WHERE thread_id=?', (thread_id,)).fetchone()
    if not row:
        return False
    try:
        return any(o.get('kind') in DATE_KINDS for o in json.loads(row['value']))
    except ValueError:
        return False


def _holds_slot(db, thread_id: str) -> bool:
    thread = db.execute('SELECT user_paused, user_archived FROM threads WHERE id=?', (thread_id,)).fetchone()
    if not thread or thread['user_archived'] or thread['user_paused']:
        return False
    if _date_stage(db, thread_id):
        return True
    last = db.execute('SELECT MAX(created_at) AS m FROM messages WHERE thread_id=?', (thread_id,)).fetchone()['m']
    return _recent(last)


def admit(thread: dict) -> bool:
    """May the agent work on this conversation now? Takes a free slot when there is one."""
    if not limited() or thread.get('platform') in (None, 'simulator'):
        return True
    cap = limit()
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        ensure(db)
        holders = []
        for row in db.execute('SELECT thread_id FROM plan_slots').fetchall():
            if _holds_slot(db, row['thread_id']):
                holders.append(row['thread_id'])
            else:
                db.execute('DELETE FROM plan_slots WHERE thread_id=?', (row['thread_id'],))
        if thread['id'] in holders:
            return True
        if _date_stage(db, thread['id']) or len(holders) < cap:
            db.execute('INSERT OR REPLACE INTO plan_slots(thread_id, admitted) VALUES(?,?)', (thread['id'], s.utcnow()))
            return True
        return False


def status(threads: list[dict] | None = None, hist: dict | None = None) -> dict | None:
    """What the panel shows: plan, slots used, and which conversations are waiting."""
    name, plan = current()
    if not plan:
        return None
    with s.connect() as db:
        ensure(db)
        admitted = {r['thread_id'] for r in db.execute('SELECT thread_id FROM plan_slots').fetchall()}
        used = sum(1 for tid in admitted if _holds_slot(db, tid))
    queued = []
    for t in threads or []:
        h = (hist or {}).get(t['id']) or []
        if (t.get('platform') not in (None, 'simulator') and h and h[-1]['sender'] == 'them'
                and not t.get('user_archived') and not t.get('user_paused') and t['id'] not in admitted):
            queued.append(t['id'])
    return {'name': name, 'label': plan['label'], 'limit': limit(), 'used': used, 'autopilot': plan['autopilot'], 'advanced_stats': plan['advanced_stats'],
            'active_days': ACTIVE_DAYS, 'queued': queued}
