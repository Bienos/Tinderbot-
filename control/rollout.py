"""Nightly rollout of new bot versions to every customer's bot (and the owner's), one at a time, with a health check each.

What "newest" means: the last successful run of the "Fly bot image" workflow on main (the repository is public, so GitHub's API
needs no secret). Its commit is the target; the Fly image for it is registry.fly.io/<image app>:git-<12 chars of the commit>.
What each bot runs: the target recorded the last time this module rolled it (table rollout_state). A bot with no record
(never rolled, or created before this existed) is simply behind and gets the target at the next run.

Safety, because every rollout restarts bots that may be answering someone right now:
- one bot at a time, a pause between them, and a Fly bot must come back healthy *and* answer the signed /internal/summary
  call (control/weekly.py) before the next one is touched;
- the first failure rolls that bot back to exactly the image it ran before (pinned by digest, never by ":latest") and stops the
  whole run, so a bad build reaches one bot, not all of them; the owner gets a mail;
- accounts without a running subscription (their bot is suspended) are skipped and picked up after they resume;
- Render bots keep serving their old version if a build fails, so those only need the alert.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime

import httpx

from control import weekly

log = logging.getLogger('uvicorn.error')
TRANSPORT = None  # tests inject an httpx.MockTransport here (GitHub)
WINDOW = (3, 5)  # local (Warsaw) hours in which the nightly run starts
WAIT_FLY, WAIT_RENDER, POLL, PAUSE = 240, 720, 10, 20  # seconds
RENDER_FAILED = {'build_failed', 'update_failed', 'pre_deploy_failed', 'canceled', 'deactivated'}


def repo_slug() -> str:
    found = re.search(r'github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?/?$', os.getenv('INSTANCE_REPO', 'https://github.com/Bienos/Tinderbot-').strip())
    return found.group(1) if found else 'Bienos/Tinderbot-'


def image_app() -> str | None:
    found = re.match(r'registry\.fly\.io/([a-z0-9-]+)[:@]', os.getenv('FLY_IMAGE', '').strip())
    return found.group(1) if found else None


def latest_build() -> dict | None:
    """The newest successfully built bot version, or None when GitHub cannot say (then nothing is rolled)."""
    try:
        with httpx.Client(timeout=15, transport=TRANSPORT, headers={'Accept': 'application/vnd.github+json'}) as c:
            r = c.get(f'https://api.github.com/repos/{repo_slug()}/actions/workflows/fly-image.yml/runs',
                      params={'branch': 'main', 'event': 'push', 'status': 'success', 'per_page': 1})
        r.raise_for_status()
        run = (r.json().get('workflow_runs') or [None])[0]
    except (httpx.HTTPError, ValueError) as exc:
        log.warning('rollout: cannot read the latest build from GitHub: %s: %s', type(exc).__name__, str(exc)[:120])
        return None
    if not run or not re.fullmatch(r'[0-9a-f]{40}', str(run.get('head_sha', ''))):
        return None
    sha, app = run['head_sha'], image_app()
    tag = 'git-' + sha[:12]
    return {'sha': sha, 'tag': tag, 'image': f'registry.fly.io/{app}:{tag}' if app else None}


def due(q, now: float) -> bool:
    """True once per night, in the early hours, when the nightly run has not started yet today."""
    local = datetime.fromtimestamp(now, weekly._tz())
    if not WINDOW[0] <= local.hour < WINDOW[1]:
        return False
    rows = q("SELECT value FROM rollout_meta WHERE key='last_run_day'", fetch=True)
    return not rows or rows[0]['value'] != local.date().isoformat()


def claim_today(q, now: float) -> None:
    day = datetime.fromtimestamp(now, weekly._tz()).date().isoformat()
    q("INSERT INTO rollout_meta(key,value) VALUES('last_run_day',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (day,))


def _record(q, service_id: str, target: str, status: str, error: str | None = None) -> None:
    q('INSERT INTO rollout_state(service_id,target,status,updated,error) VALUES(?,?,?,?,?) '
      'ON CONFLICT(service_id) DO UPDATE SET target=excluded.target, status=excluded.status, updated=excluded.updated, error=excluded.error',
      (service_id, target, status, time.time(), error))


def mark_current(q, service_id: str) -> None:
    """A bot just created from the newest image is already on the target: do not restart it tonight for nothing."""
    build = latest_build()
    if build:
        _record(q, service_id, build['sha'], 'ok')


def candidates(q, owner_service_id: str) -> list[dict]:
    """Every bot that should follow new versions, in rollout order: Fly bots, Render customers, the owner's own last."""
    rows = q("SELECT id,email,render_service_id,instance_url,sso_secret,plan_status,comped FROM accounts "
             "WHERE render_service_id IS NOT NULL AND render_service_id<>'' AND status='active' ORDER BY id", fetch=True)
    items = [{'service_id': r['render_service_id'], 'acc': r, 'owner': r['render_service_id'] == owner_service_id} for r in rows]
    if owner_service_id and not any(i['service_id'] == owner_service_id for i in items):
        items.append({'service_id': owner_service_id, 'acc': None, 'owner': True})
    rank = lambda i: (2 if i['owner'] else 0 if i['service_id'].startswith('fly:') else 1)
    return sorted(items, key=rank)  # sorted is stable: oldest account first inside each group


def _wait_fly(app: str, acc: dict, base_for, *, sleep, health) -> None:
    from control import fly
    deadline = time.monotonic() + WAIT_FLY
    last = 'did not become healthy'
    while time.monotonic() < deadline:
        try:
            if fly.deploy_status(app) == 'live':
                health(acc, base_for)
                return
        except Exception as exc:
            last = f'{type(exc).__name__}: {str(exc)[:100]}'
        sleep(POLL)
    raise RuntimeError(last)


def default_health(acc: dict, base_for) -> None:
    """The new bot answers the control service's signed call, i.e. it runs and speaks the contract."""
    if acc and acc.get('sso_secret') and acc.get('instance_url'):
        weekly.fetch(acc['sso_secret'], base_for(acc))


def _roll_fly(item: dict, image: str, base_for, *, sleep, health) -> str:
    from control import fly
    app = item['service_id'][4:]
    previous = fly.current_image(app)
    if fly.update_image(app, image) == 'unchanged':
        return 'unchanged'
    try:
        _wait_fly(app, item['acc'], base_for, sleep=sleep, health=health)
    except Exception as exc:
        try:
            fly.update_image(app, previous)  # back to exactly what ran before
        except Exception as back:
            raise RuntimeError(f'{exc}; ROLLBACK FAILED: {type(back).__name__}: {str(back)[:80]}') from None
        raise RuntimeError(f'{exc}; rolled back') from None
    return 'updated'


def _roll_render(service_id: str, *, sleep) -> str:
    from control import provision
    provision.trigger_deploy(service_id)
    deadline = time.monotonic() + WAIT_RENDER
    status = 'unknown'
    while time.monotonic() < deadline:
        sleep(POLL)
        status = provision.deploy_status(service_id)
        if status == 'live':
            return 'updated'
        if status in RENDER_FAILED:
            raise RuntimeError(f'deploy {status} (the previous version keeps serving)')
    raise RuntimeError(f'deploy still {status} after {WAIT_RENDER // 60} minutes')


def run(q, *, has_access, base_for, owner_service_id: str = '', alert=None, force: bool = False, dry_run: bool = False,
        only: str | None = None, sleep=time.sleep, health=default_health) -> dict:
    """One pass over all bots. force re-rolls bots that are already on the target; dry_run only lists what would be done;
    only='fly' or 'render' limits the run to that provider (the others are left out of the result)."""
    from control import provision
    target = latest_build()
    if not target:
        return {'result': 'no build found', 'items': []}
    state = {r['service_id']: r for r in q('SELECT * FROM rollout_state', fetch=True)}
    items, aborted = [], False
    for item in candidates(q, owner_service_id):
        sid, acc = item['service_id'], item['acc']
        row = {'service_id': sid, 'provider': 'fly' if sid.startswith('fly:') else 'render', 'owner': item['owner']}
        if only and row['provider'] != only:
            continue
        if not force and state.get(sid, {}).get('target') == target['sha'] and state[sid].get('status') == 'ok':
            items.append({**row, 'result': 'up to date'})
            continue
        if acc and not item['owner'] and not (acc.get('comped') or has_access(acc)):
            items.append({**row, 'result': 'skipped: no running subscription'})
            continue
        if not provision.can_query(sid) or (row['provider'] == 'fly' and not target['image']):
            items.append({**row, 'result': 'skipped: hosting API is not configured'})
            continue
        if dry_run:
            items.append({**row, 'result': 'would update'})
            continue
        if aborted:
            items.append({**row, 'result': 'skipped: run stopped after a failure'})
            continue
        try:
            outcome = _roll_fly(item, target['image'], base_for, sleep=sleep, health=health) if row['provider'] == 'fly' else _roll_render(sid, sleep=sleep)
        except Exception as exc:
            _record(q, sid, target['sha'], 'failed', f'{type(exc).__name__}: {str(exc)[:200]}')
            items.append({**row, 'result': f'failed: {str(exc)[:160]}'})
            who = (acc or {}).get('email') or 'owner'
            log.error('rollout: %s (%s) failed: %s', sid, who, str(exc)[:200])
            if alert:
                alert(f'Rollout zatrzymany: {sid}', f'Bot {sid} ({who}) nie przeszedł na wersję {target["tag"]}.\n\nPowód: {str(exc)[:300]}\n\n'
                      'Pozostałe boty nie zostały ruszone. Sprawdź /admin/rollout, a po naprawie uruchom POST /admin/rollout/run.')
            aborted = True
            continue
        _record(q, sid, target['sha'], 'ok')
        items.append({**row, 'result': outcome})
        if outcome == 'updated':
            sleep(PAUSE)
    return {'result': 'aborted' if aborted else 'done', 'target': {k: target[k] for k in ('sha', 'tag')}, 'items': items}
