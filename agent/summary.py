"""Weekly summary of one instance: counts only, never names, messages or any other conversation content.

The control service (control/weekly.py) asks every customer's bot for this once a week and puts the numbers into the
"Twój tydzień w Winq" e-mail. The same document says whether the bot is healthy (Tinder connected, synchronizing,
not paused), so the control service can also check the whole fleet with it.

Definitions match the dashboard's statistics tab (static/dashboard.js):
- a run is a stretch of consecutive messages from one side;
- one of our runs is "answered" when the next run is the other person's;
- a run younger than 6 hours with no answer is not counted yet (it has not had a fair chance).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from agent import storage as s

DAY = 86400.0
FAIR_CHANCE = 6 * 3600.0
STALE_SYNC = 6 * 3600.0  # polling every few minutes: a gap this long means something is wrong
MEETING_KINDS = ('date_confirmed',)
CONTACT_KINDS = ('instagram_shared', 'phone_shared')


def _ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def _runs(history: list[dict]) -> list[dict]:
    runs: list[dict] = []
    for m in sorted(history, key=lambda m: _ts(m.get('created_at')) or 0):
        ts = _ts(m.get('created_at'))
        if ts is None:
            continue
        side = 'you' if m['sender'] == 'you' else 'them'
        if runs and runs[-1]['side'] == side:
            runs[-1]['last'] = ts
        else:
            runs.append({'side': side, 'first': ts, 'last': ts})
    return runs


def _window(threads: list[dict], lo: float, hi: float, now: float) -> dict:
    out = {'matches': 0, 'messages_you': 0, 'messages_them': 0, 'asked': 0, 'answered': 0}
    for t in threads:
        if lo <= t['matched'] < hi:
            out['matches'] += 1
        for ts, side in t['messages']:
            if lo <= ts < hi:
                out['messages_you' if side == 'you' else 'messages_them'] += 1
        runs = t['runs']
        for i, run in enumerate(runs):
            if run['side'] != 'you' or not lo <= run['last'] < hi:
                continue
            answered = i + 1 < len(runs)
            if answered or now - run['last'] > FAIR_CHANCE:
                out['asked'] += 1
                out['answered'] += int(answered)
    out['reply_rate'] = round(100 * out['answered'] / out['asked']) if out['asked'] >= 5 else None
    return out


def _load(now: float) -> tuple[list[dict], list[dict]]:
    by_thread = s.messages_by_thread()
    profiles = {}
    for r in s.rows('SELECT thread_id,value FROM tinder_threads'):
        try:
            profiles[r['thread_id']] = (json.loads(r['value']).get('profile') or {})
        except ValueError:
            pass
    threads = []
    for t in s.threads():
        history = by_thread.get(t['id'], [])
        runs = _runs(history)
        msgs = [(_ts(m['created_at']), 'you' if m['sender'] == 'you' else 'them') for m in history if _ts(m.get('created_at')) is not None]
        matched = _ts(profiles.get(t['id'], {}).get('matched_at')) or (msgs[0][0] if msgs else 0)
        threads.append({'row': t, 'history': history, 'runs': runs, 'messages': msgs, 'matched': matched})
    return threads, s.rows('SELECT kind,created_at FROM notifications')


def _events(notes: list[dict], kinds: tuple, lo: float, hi: float) -> int:
    return sum(1 for n in notes if n['kind'] in kinds and lo <= (_ts(n['created_at']) or 0) < hi)


def _health(now: float) -> dict:
    from agent import runtime as rt, service, tinder
    cfg = rt.settings()
    rows = s.rows("SELECT * FROM connections WHERE id LIKE 'tinder:%'")
    conns = []
    for r in rows:
        v = json.loads(r['value'])
        conns.append({'enabled': bool(r['enabled']), 'error': v.get('error'), 'last_sync': _ts(v.get('last_sync')),
                      'blocked_until': float(v.get('blocked_until', 0) or 0), 'import_done': bool(v.get('initial_import_done')),
                      'next_poll': float(v.get('next_poll', 0) or 0), 'idle_rounds': v.get('idle_rounds')})
    unreadable = threads_read = threads_total = 0
    for r in s.rows('SELECT value FROM tinder_threads'):
        try:
            v = json.loads(r['value'])
        except ValueError:
            continue
        threads_total += 1
        threads_read += bool(v.get('last_read'))
        unreadable += bool(v.get('read_failed'))
    requests_hour = s.rows('SELECT COUNT(*) n FROM tinder_requests WHERE ts>?', (now - 3600,))[0]['n']
    requests_minute = s.rows('SELECT COUNT(*) n FROM tinder_requests WHERE ts>?', (now - 60,))[0]['n']
    issues: list[str] = []
    paused = bool(cfg.get('paused'))
    live = [c for c in conns if c['enabled']]
    last_sync = max((c['last_sync'] for c in conns if c['last_sync']), default=None)
    if not conns or (not live and not any(c['error'] for c in conns)):
        issues.append('tinder_not_connected')
    for c in conns:
        if c['error']:
            issues.append('tinder_error:' + str(c['error']))
        elif c['enabled'] and not paused and (c['last_sync'] is None or now - c['last_sync'] > STALE_SYNC) and not c['blocked_until'] > now:
            issues.append('sync_stale')
    if paused:
        issues.append('agent_paused')
    if service.WORKER.get('error'):
        issues.append('worker_error')
    problem = any(i.startswith('tinder_error') or i in ('sync_stale', 'worker_error', 'tinder_not_connected') for i in issues)
    return {'status': 'problem' if problem else 'attention' if issues else 'ok', 'issues': sorted(set(issues)),
            'tinder': {'configured': tinder.configured(), 'connections': len(conns), 'unreadable_threads': unreadable,
                       # Diagnostics for a synchronization that does not finish: progress, budget use and waiting times.
                       'threads_read': threads_read, 'threads_total': threads_total, 'requests_last_hour': requests_hour,
                       'requests_last_minute': requests_minute, 'import_done': any(c['import_done'] for c in conns),
                       'blocked_for_min': max((round(max(0, c['blocked_until'] - now) / 60, 1) for c in conns), default=0),
                       'next_poll_in_min': max((round(max(0, c['next_poll'] - now) / 60, 1) for c in conns), default=0), 'connected': bool(live) and not any(c['error'] for c in live),
                       'last_sync_age_min': None if last_sync is None else max(0, round((now - last_sync) / 60))},
            'agent': {'paused': paused, 'mode': cfg.get('mode'), 'worker_running': bool(service.WORKER.get('running'))}}


def weekly(now: float | None = None, days: int = 7) -> dict:
    from agent import strategy, plans, runtime as rt
    now = time.time() if now is None else now
    span = days * DAY
    threads, notes = _load(now)
    this = _window(threads, now - span, now + 1, now)
    prev = _window(threads, now - 2 * span, now - span, now)
    for w, (lo, hi) in ((this, (now - span, now + 1)), (prev, (now - 2 * span, now - span))):
        w['meetings'] = _events(notes, MEETING_KINDS, lo, hi)
        w['contacts'] = _events(notes, CONTACT_KINDS, lo, hi)
        w['sent_by_agent'] = sum(r['n'] for r in s.rows("SELECT COUNT(*) n FROM actions WHERE status='sent' AND updated>=? AND updated<?", (lo, hi)))
    cfg = rt.settings()
    outcomes = {r['thread_id']: json.loads(r['value']) for r in s.rows('SELECT thread_id,value FROM outcome_state')}
    needs = invite = conversations = 0
    for t in threads:
        row, history = t['row'], t['history']
        if row['user_archived'] or row['user_paused']:
            continue
        if history:
            conversations += 1
            if history[-1]['sender'] != 'you':
                needs += 1
            if strategy.analyze(history, cfg, outcomes.get(row['id'], [])).get('stage') == 'invite':
                invite += 1
    return {'version': 1, 'generated_at': datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds'), 'period_days': days,
            'this': this, 'prev': prev,
            'now': {'needs_reply': needs, 'invite_window': invite, 'conversations': conversations, 'matches_total': len(threads)},
            'plan': {'name': plans.current()[0], 'advanced_stats': plans.current()[1] is None or bool(plans.current()[1].get('advanced_stats'))},
            'health': _health(now)}
