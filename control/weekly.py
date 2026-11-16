"""Weekly summary e-mail and fleet check.

Every customer's bot (its own server, see docs/CUSTOMER_INSTANCES.md) answers GET /internal/summary with counts and health
codes. This module asks each one, signed with that customer's SSO secret, and turns the answer into the Monday e-mail
(control/mailer.py: weekly_spec). The same call is the fleet check: it proves per customer that the server is reachable,
Tinder is connected and the data is fresh.

Sending is safe to repeat and to run from several processes: an account is claimed in the database before anything is
fetched, and marked as sent only after the mail was handed to the SMTP server. A bot that cannot be reached is retried on
the next run (every half hour) for two days after Monday 08:00; then the week is skipped. Nothing here ever carries names or message text.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from control import mailer

log = logging.getLogger('uvicorn.error')
TRANSPORT = None  # tests inject an httpx.MockTransport here
SLOT_HOUR = 8  # Monday, 08:00 Warsaw time: first message of the week; later runs catch up
MIN_AGE_DAYS = 3  # a brand-new account has nothing to summarize yet
WINDOW_HOURS = 48  # after Monday 08:00 an unreachable bot is retried for two days; then the week is skipped (no Friday surprises)
FETCH_TIMEOUT = 15
CLAIM_SECONDS = 600  # a claim older than this is abandoned (the process that made it died)


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('Europe/Warsaw')
    except Exception:  # no tz database in a minimal image: UTC+1 is right outside summer time and an hour off inside it
        return timezone(timedelta(hours=1))


def slot_start(now: float) -> float:
    """The most recent Monday 08:00 (Warsaw) at or before `now`, as a Unix time. An account is due when it was not sent since then."""
    local = datetime.fromtimestamp(now, _tz())
    monday = (local - timedelta(days=local.weekday())).replace(hour=SLOT_HOUR, minute=0, second=0, microsecond=0)
    if monday > local:
        monday -= timedelta(days=7)
    return monday.timestamp()


def signed_headers(secret: str, audience: str, now: float | None = None, purpose: str = 'summary') -> dict:
    stamp = int(time.time() if now is None else now)
    sig = hmac.new(secret.encode(), f"{purpose}:{stamp}:{audience.rstrip('/')}".encode(), hashlib.sha256).hexdigest()
    return {'X-Winq-Ts': str(stamp), 'X-Winq-Sig': sig}


def fetch(secret: str, base_url: str, days: int = 7) -> dict:
    """The bot's summary document. Raises on any failure (unreachable, refused, not our document)."""
    base = base_url.rstrip('/')
    with httpx.Client(timeout=FETCH_TIMEOUT, transport=TRANSPORT, follow_redirects=False) as c:
        r = c.get(f'{base}/internal/summary', params={'days': days}, headers=signed_headers(secret, base))
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}')
    data = r.json()
    if not isinstance(data, dict) or 'this' not in data or 'health' not in data:
        raise RuntimeError('unexpected answer (is the bot on an older version?)')
    return data


def _unsub_token(q, acc: dict) -> str:
    if acc.get('unsub_token'):
        return acc['unsub_token']
    q('UPDATE accounts SET unsub_token=? WHERE id=? AND unsub_token IS NULL', (secrets.token_urlsafe(24), acc['id']))
    return q('SELECT unsub_token FROM accounts WHERE id=?', (acc['id'],), fetch=True)[0]['unsub_token']


def _note(q, acc_id: int, text: str) -> None:
    q('UPDATE accounts SET weekly_note=? WHERE id=?', (text[:200], acc_id))


def candidates(q) -> list[dict]:
    return q("SELECT * FROM accounts WHERE status='active' AND instance_url IS NOT NULL AND sso_secret IS NOT NULL "
             'AND COALESCE(weekly_summary,1)=1 AND withdrawn_at IS NULL ORDER BY id', fetch=True)


def run(q, now: float, *, base_for, has_access, origin: str, force: bool = False, dry_run: bool = False, email: str | None = None) -> list[dict]:
    """One pass over all customers. `base_for(acc)` is the address of that customer's bot, `has_access(acc)` says whether
    they have a running subscription. force ignores the weekly slot and the minimum age; dry_run composes but sends and marks nothing."""
    slot, results = slot_start(now), []
    ready = mailer.configured() and mailer.sender_problem() is None
    for acc in candidates(q):
        who = {'email': acc['email']}
        if email and acc['email'] != email.strip().lower():
            continue
        if not has_access(acc):
            results.append({**who, 'result': 'skipped: no access'})
            continue
        if not force and now - float(acc.get('created') or 0) < MIN_AGE_DAYS * 86400:
            results.append({**who, 'result': 'skipped: account too new'})
            continue
        if not force and now - slot > WINDOW_HOURS * 3600:
            results.append({**who, 'result': 'skipped: outside the Monday window'})
            continue
        if not force and float(acc.get('weekly_sent_at') or 0) >= slot:
            results.append({**who, 'result': 'skipped: already sent this week'})
            continue
        if not ready and not dry_run:
            results.append({**who, 'result': 'skipped: mail is not configured'})
            continue
        claim = None
        if not dry_run:
            claim = now + secrets.randbelow(10 ** 6) / 1e9
            q('UPDATE accounts SET weekly_claim=? WHERE id=? AND COALESCE(weekly_claim,0)<?', (claim, acc['id'], now - CLAIM_SECONDS))
            if q('SELECT weekly_claim FROM accounts WHERE id=?', (acc['id'],), fetch=True)[0]['weekly_claim'] != claim:
                results.append({**who, 'result': 'skipped: another run has it'})
                continue
        try:
            summary = fetch(acc['sso_secret'], base_for(acc))
            spec = mailer.weekly_spec(summary, origin, f"{origin}/wypisz-sie?t={_unsub_token(q, acc)}")
            if dry_run:
                results.append({**who, 'result': 'dry run', 'subject': spec['subject'], 'health': summary['health']['status'], 'issues': summary['health']['issues']})
                continue
            sent = mailer.send_spec(acc['email'], spec)
        except Exception as exc:  # the reason only: never the signature, the body or the secret
            if claim is not None:
                q('UPDATE accounts SET weekly_claim=NULL WHERE id=?', (acc['id'],))
                _note(q, acc['id'], f'failed {time.strftime("%Y-%m-%d %H:%M", time.gmtime(now))}: {type(exc).__name__}: {str(exc)[:120]}')
            log.warning('weekly summary for account %s failed: %s: %s', acc['id'], type(exc).__name__, str(exc)[:160])
            results.append({**who, 'result': f'failed: {type(exc).__name__}: {str(exc)[:120]}'})
            continue
        if sent:
            q('UPDATE accounts SET weekly_sent_at=?, weekly_claim=NULL, weekly_note=? WHERE id=?', (now, 'sent', acc['id']))
            results.append({**who, 'result': 'sent', 'subject': spec['subject']})
        else:
            q('UPDATE accounts SET weekly_claim=NULL WHERE id=?', (acc['id'],))
            results.append({**who, 'result': 'not sent: mail is not configured'})
    return results


def check_fleet(q, *, base_for, has_access, workers: int = 8) -> list[dict]:
    """Health of every customer's bot as the bot itself reports it. A bot that does not answer is itself a finding."""
    accounts = [a for a in candidates(q)]

    def one(acc: dict) -> dict:
        started = time.time()
        row = {'email': acc['email'], 'instance': base_for(acc), 'access': bool(has_access(acc)), 'weekly_sent_at': acc.get('weekly_sent_at'),
               'weekly_note': acc.get('weekly_note')}
        try:
            data = fetch(acc['sso_secret'], base_for(acc), days=7)
        except Exception as exc:
            return {**row, 'reachable': False, 'error': f'{type(exc).__name__}: {str(exc)[:120]}', 'ms': round((time.time() - started) * 1000)}
        h = data['health']
        return {**row, 'reachable': True, 'ms': round((time.time() - started) * 1000), 'status': h['status'], 'issues': h['issues'],
                'tinder_connected': h['tinder']['connected'], 'last_sync_age_min': h['tinder']['last_sync_age_min'],
                'agent_paused': h['agent']['paused'], 'worker_running': h['agent']['worker_running'],
                'conversations': data['now']['conversations']}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, accounts))
