"""Customer bots on Fly.io (PROVISION_BACKEND=fly): one app, one volume and one always-on Machine per customer.

Isolation is the same as on Render: each customer has their own process, database file and keys. Secrets
(dashboard token, encryption key, SSO secret, model key) are Fly app secrets, never part of the Machine config.

Settings on the control service:
  FLY_API_TOKEN   org token (Fly dashboard > organization > Tokens), the full "FlyV1 fm2_..." string
  FLY_ORG         organization slug, e.g. "personal"
  FLY_IMAGE       image for new bots, e.g. registry.fly.io/<image-app>:latest (built by .github/workflows/fly-image.yml)
  FLY_REGION      default "fra" (Frankfurt)
  FLY_MEMORY_MB   default 256 (multiples of 256)
Model settings are copied server-side from the template bot on Render (INSTANCE_TEMPLATE_SERVICE_ID), so the model
key never sits in this service's own settings.
"""
from __future__ import annotations

import os
import secrets
import time

import httpx

API = 'https://api.machines.dev/v1'
TRANSPORT = None  # tests inject an httpx.MockTransport here
PORT = 8080
SECRET_KEYS = ('DASHBOARD_TOKEN', 'TOKEN_ENCRYPTION_KEY', 'SSO_SECRET', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY')


class FlyError(RuntimeError):
    pass


def api_ready() -> bool:
    return bool(os.getenv('FLY_API_TOKEN', '').strip())


def enabled() -> bool:
    from control import provision
    return (api_ready() and bool(os.getenv('FLY_ORG', '').strip()) and bool(os.getenv('FLY_IMAGE', '').strip())
            and provision.api_ready() and bool(os.getenv('INSTANCE_TEMPLATE_SERVICE_ID')))


def _auth() -> str:
    token = os.environ['FLY_API_TOKEN'].strip()
    return token if token.startswith('FlyV1 ') else 'Bearer ' + token


def _client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=60, transport=TRANSPORT,
                        headers={'Authorization': _auth(), 'Accept': 'application/json'})


def _check(r: httpx.Response, what: str) -> httpx.Response:
    if r.status_code >= 400:
        # Fly error bodies carry no secrets; keep them short in our logs.
        raise FlyError(f'{what}: HTTP {r.status_code} {r.text[:200]}')
    return r


def machine_config(image: str, env: dict, volume_id: str, account_id: int, host: str) -> dict:
    return {
        'image': image,
        'env': env,
        'guest': {'cpu_kind': 'shared', 'cpus': 1, 'memory_mb': int(os.getenv('FLY_MEMORY_MB', '256'))},
        'mounts': [{'volume': volume_id, 'path': '/var/data'}],
        # Always on: the bot polls Tinder and writes drafts even when nobody has the panel open.
        'services': [{'protocol': 'tcp', 'internal_port': PORT, 'autostop': 'off', 'autostart': True,
                      'min_machines_running': 1,
                      'ports': [{'port': 443, 'handlers': ['tls', 'http']},
                                {'port': 80, 'handlers': ['http'], 'force_https': True}]}],
        # The bot only answers requests addressed to its own public name, so the check says which name it means.
        'checks': {'health': {'type': 'http', 'port': PORT, 'method': 'GET', 'path': '/health',
                              'headers': [{'name': 'Host', 'values': [host]}],
                              'interval': '15s', 'timeout': '5s', 'grace_period': '20s'}},
        'restart': {'policy': 'always'},
        'metadata': {'fly_platform_version': 'v2', 'fly_process_group': 'app', 'iskra_account': str(account_id)},
    }


def create_instance(account_id: int) -> dict:
    """App, public address, secrets, volume, Machine. On any failure the half-made app is removed again."""
    from control import provision
    name = f'iskra-u{account_id}-{secrets.token_hex(3)}'
    region = os.getenv('FLY_REGION', 'fra').strip() or 'fra'
    origin = f'https://{name}.fly.dev'
    sso_secret = secrets.token_urlsafe(32)
    env = provision.instance_env(sso_secret, provision.model_env())
    hidden = {k: v for k, v in env.items() if k in SECRET_KEYS}
    public = {k: v for k, v in env.items() if k not in SECRET_KEYS}
    public.update({'PUBLIC_ORIGIN': origin, 'PORT': str(PORT)})
    with _client() as c:
        _check(c.post('/apps', json={'name': name, 'org_slug': os.environ['FLY_ORG'].strip(), 'idempotency_key': name}),
               'create app')
        try:
            for kind in ('shared_v4', 'v6'):  # a new app has no address until one is assigned
                _check(c.post(f'/apps/{name}/ip_assignments', json={'type': kind}), 'assign ' + kind)
            stored = _check(c.post(f'/apps/{name}/secrets', json={'values': hidden}), 'set secrets').json()
            version = stored.get('version', stored.get('Version'))
            volume = _check(c.post(f'/apps/{name}/volumes', json={
                'name': 'data', 'region': region, 'size_gb': 1, 'encrypted': True,
                'auto_backup_enabled': True, 'snapshot_retention': 7}), 'create volume').json()
            body = {'region': region, 'config': machine_config(os.environ['FLY_IMAGE'].strip(), public, volume['id'], account_id,
                                                                 f'{name}.fly.dev')}
            if version is not None:
                body['min_secrets_version'] = version
            machine = _check(c.post(f'/apps/{name}/machines', json=body), 'create machine').json()
            try:  # best effort: the account page follows the progress anyway
                c.get(f"/apps/{name}/machines/{machine['id']}/wait", params={'state': 'started', 'timeout': 60}, timeout=75)
            except httpx.HTTPError:
                pass
        except Exception:
            try:
                c.delete(f'/apps/{name}', params={'force': 'true'})
            except httpx.HTTPError:
                pass
            raise
    return {'service_id': 'fly:' + name, 'url': origin, 'sso_secret': sso_secret}


def _machine(c: httpx.Client, app: str) -> dict:
    machines = _check(c.get(f'/apps/{app}/machines'), 'list machines').json()
    if not machines:
        raise FlyError(f'{app}: no machine')
    return machines[0]


def set_suspended(app: str, suspended: bool) -> None:
    """Lapsed subscription: stop the bot and keep it stopped (no auto-start on a stray request). Returned: start."""
    with _client() as c:
        m = _machine(c, app)
        config = m['config']
        for service in config.get('services', []):
            service['autostart'] = not suspended
        body = {'config': config, 'current_version': m.get('version'), 'skip_launch': suspended}
        _check(c.post(f"/apps/{app}/machines/{m['id']}", json=body), 'update machine')
        if suspended:
            r = c.post(f"/apps/{app}/machines/{m['id']}/stop", json={})
            if r.status_code >= 400 and 'not' not in r.text.lower():  # already stopped is fine
                _check(r, 'stop machine')


def deploy_status(app: str) -> str:
    """The Machine's state in the words the account page already understands (Render's deploy statuses)."""
    with _client() as c:
        machines = _check(c.get(f'/apps/{app}/machines'), 'list machines').json()
    if not machines:
        return 'created'
    m = machines[0]
    state = m.get('state', '')
    if state == 'created':
        return 'created'
    if state in ('starting', 'replacing', 'updating', 'launch_failed'):
        return 'update_failed' if state == 'launch_failed' else 'update_in_progress'
    if state == 'failed':
        return 'update_failed'
    if state == 'started':
        checks = m.get('checks') or []
        return 'live' if all(ch.get('status') == 'passing' for ch in checks) else 'update_in_progress'
    return 'live' if state in ('stopped', 'suspended') else 'unknown'


def update_image(app: str, image: str) -> str:
    """Move one bot to a new image. The volume (and its data) stays attached; the Machine restarts."""
    with _client() as c:
        m = _machine(c, app)
        config = m['config']
        if config.get('image') == image and m.get('image_ref', {}).get('tag') not in (None, 'latest'):
            return 'unchanged'
        config['image'] = image
        _check(c.post(f"/apps/{app}/machines/{m['id']}", json={'config': config, 'current_version': m.get('version')}),
               'update machine')
    return 'updated'


def update_all(apps: list[str], image: str, pause: float = 1.2) -> dict:
    """Rolling update, one bot at a time and within Fly's per-app rate limits."""
    results = {}
    for app in apps:
        try:
            results[app] = update_image(app, image)
        except (FlyError, httpx.HTTPError) as exc:
            results[app] = 'failed: ' + str(exc)[:160]
        time.sleep(pause)
    return results
