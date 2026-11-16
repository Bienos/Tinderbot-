"""Automatic per-customer instances on Render (option 4: one isolated server per customer).

After a paid checkout the control service creates the customer's own web service with a persistent disk,
fresh per-instance secrets (encryption key, dashboard token, SSO secret) and links the shared environment
group that holds the model API key, so that key never lives in the control service. Cancelled subscriptions
suspend the instance; reactivated ones resume it.

Needs RENDER_API_KEY and RENDER_OWNER_ID (workspace id, tea-...), plus where the model key comes from:
RENDER_ENV_GROUP_ID (evg-..., linked to every instance) or INSTANCE_TEMPLATE_SERVICE_ID (srv-..., an existing
instance whose model settings are copied server-side, so the key never passes through anyone's hands).
The owner's own, already running instance is linked instead of created (OWNER_SERVICE_ID).
"""
from __future__ import annotations

import base64
import os
import re
import secrets

import httpx

API = 'https://api.render.com/v1'
TRANSPORT = None  # tests inject an httpx.MockTransport here


COPY_KEYS = ('LLM_PROVIDER', 'ANTHROPIC_API_KEY', 'ANTHROPIC_MODEL')


def api_ready() -> bool:
    return all(os.getenv(k) for k in ('RENDER_API_KEY', 'RENDER_OWNER_ID'))


def backend() -> str:
    """Where new customers' bots are created: 'render' (default) or 'fly'. Existing instances keep their provider:
    a Fly instance id is stored as 'fly:<app>', a Render one as the plain service id."""
    return os.getenv('PROVISION_BACKEND', 'render').strip().lower()


def render_enabled() -> bool:
    return api_ready() and bool(os.getenv('RENDER_ENV_GROUP_ID') or os.getenv('INSTANCE_TEMPLATE_SERVICE_ID'))


def enabled() -> bool:
    if backend() == 'fly':
        from control import fly
        return fly.enabled()
    return render_enabled()


def model_env() -> dict:
    """Model settings for a new bot, copied server-side from the template instance on Render."""
    with _client() as c:
        return template_env(c)


def _client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=30, transport=TRANSPORT,
                        headers={'Authorization': 'Bearer ' + os.environ['RENDER_API_KEY'], 'Accept': 'application/json'})


def _key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')


def template_env(c: httpx.Client) -> dict:
    """Model settings of the template instance, read straight from Render."""
    r = c.get(f"/services/{os.environ['INSTANCE_TEMPLATE_SERVICE_ID']}/env-vars", params={'limit': 100})
    r.raise_for_status()
    found = {}
    for item in r.json():
        ev = item.get('envVar', item)
        if ev.get('key') in COPY_KEYS and ev.get('value'):
            found[ev['key']] = ev['value']
    if 'ANTHROPIC_API_KEY' not in found:
        raise RuntimeError('template instance has no ANTHROPIC_API_KEY')
    return found


def instance_env(sso_secret: str, extra_env: dict | None = None) -> dict:
    """Settings every customer bot gets, whichever provider runs it. Fresh secrets per instance."""
    return {
        'WEB_CONCURRENCY': '1', 'AGENT_DB_PATH': '/var/data/agent.db',
        'SEED_SIMULATOR': 'false', 'DATING_AGENT_SOURCE': 'fixture', 'WORKER_ENABLED': 'true', 'COOKIE_SECURE': 'true',
        'TINDER_ENABLED': 'true', 'TINDER_REQUESTS_PER_MINUTE': '30', 'TINDER_REQUESTS_PER_HOUR': '300',
        'DASHBOARD_TOKEN': secrets.token_urlsafe(32), 'TOKEN_ENCRYPTION_KEY': _key(), 'SSO_SECRET': sso_secret,
        'CONTROL_ORIGIN': os.getenv('PUBLIC_ORIGIN', '').rstrip('/'),
        **(extra_env or {}),
    }


def service_body(name: str, sso_secret: str, extra_env: dict | None = None) -> dict:
    env = {'PYTHON_VERSION': '3.12.14', **instance_env(sso_secret, extra_env)}
    return {
        'type': 'web_service', 'name': name, 'ownerId': os.environ['RENDER_OWNER_ID'],
        'repo': os.getenv('INSTANCE_REPO', 'https://github.com/Bienos/Tinderbot-'), 'branch': os.getenv('INSTANCE_BRANCH', 'main'),
        'autoDeployTrigger': 'off',
        'envVars': [{'key': k, 'value': v} for k, v in env.items()],
        'serviceDetails': {
            'runtime': 'python', 'plan': os.getenv('INSTANCE_PLAN', 'starter'), 'region': 'frankfurt', 'numInstances': 1,
            'healthCheckPath': '/health',
            'envSpecificDetails': {
                'buildCommand': 'python -m pip install -r requirements.lock',
                'startCommand': 'python -m uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1 --no-access-log '
                                '--limit-concurrency 100 --timeout-keep-alive 5'},
            'disk': {'name': 'conversation-data', 'mountPath': '/var/data', 'sizeGB': 1},
        },
    }


def create_instance(account_id: int, plan: str | None = None) -> dict:
    if backend() == 'fly':
        from control import fly
        return fly.create_instance(account_id, plan)
    return render_create_instance(account_id, plan)


def set_plan(service_id: str, plan: str, conversations: str | None = None) -> None:
    """Give a running bot another plan (its PLAN setting decides how many conversations it handles).
    `conversations` sets PLAN_CONVERSATIONS in the same restart: a number overrides the plan's limit (the retention bonus),
    an empty string removes the override, None leaves it alone."""
    if service_id.startswith('fly:'):
        from control import fly
        values = {'PLAN': plan}
        if conversations is not None:
            values['PLAN_CONVERSATIONS'] = conversations  # the bot treats an empty value as "use the plan's own limit"
        return fly.set_env(service_id[4:], values)
    with _client() as c:
        c.put(f'/services/{service_id}/env-vars/PLAN', json={'value': plan}).raise_for_status()
        if conversations:
            c.put(f'/services/{service_id}/env-vars/PLAN_CONVERSATIONS', json={'value': conversations}).raise_for_status()
        elif conversations == '':
            r = c.delete(f'/services/{service_id}/env-vars/PLAN_CONVERSATIONS')
            if r.status_code not in (200, 202, 204, 404):
                r.raise_for_status()
        c.post(f'/services/{service_id}/deploys', json={}).raise_for_status()


def render_create_instance(account_id: int, plan: str | None = None) -> dict:
    """Create the service, link the shared env group and redeploy so the group's variables are loaded."""
    sso_secret = secrets.token_urlsafe(32)
    name = f'winq-bot-u{account_id}-{secrets.token_hex(2)}'
    group = os.getenv('RENDER_ENV_GROUP_ID')
    with _client() as c:
        extra = None if group else template_env(c)
        if plan:
            extra = {**(extra or {}), 'PLAN': plan}
        r = c.post('/services', json=service_body(name, sso_secret, extra))
        r.raise_for_status()
        service = r.json()['service']
        sid, url = service['id'], service['serviceDetails']['url'].rstrip('/')
        if group:
            c.post(f'/env-groups/{group}/services/{sid}').raise_for_status()
            c.post(f'/services/{sid}/deploys', json={}).raise_for_status()
    return {'service_id': sid, 'url': url, 'sso_secret': sso_secret}


def link_existing(service_id: str) -> dict:
    """Connect an instance that already runs (the owner's): fresh SSO secret, control origin, redeploy."""
    sso_secret = secrets.token_urlsafe(32)
    with _client() as c:
        r = c.get(f'/services/{service_id}')
        r.raise_for_status()
        url = r.json()['serviceDetails']['url'].rstrip('/')
        for key, value in (('SSO_SECRET', sso_secret), ('CONTROL_ORIGIN', os.getenv('PUBLIC_ORIGIN', '').rstrip('/'))):
            if value:
                c.put(f'/services/{service_id}/env-vars/{key}', json={'value': value}).raise_for_status()
        c.post(f'/services/{service_id}/deploys', json={}).raise_for_status()
    return {'url': url, 'sso_secret': sso_secret}


def delete_instance(service_id: str) -> None:
    """Remove a customer's bot and its disk for good, on whichever provider runs it. Already gone counts as done."""
    if service_id.startswith('fly:'):
        from control import fly
        return fly.delete_instance(service_id[4:])
    if not re.fullmatch(r'srv-[a-z0-9]+', service_id):
        raise RuntimeError('refusing to delete a service with an unexpected id')
    with _client() as c:
        r = c.delete(f'/services/{service_id}')
        if r.status_code not in (200, 202, 204, 404):
            r.raise_for_status()


def set_suspended(service_id: str, suspended: bool) -> None:
    if service_id.startswith('fly:'):
        from control import fly
        return fly.set_suspended(service_id[4:], suspended)
    with _client() as c:
        c.post(f"/services/{service_id}/{'suspend' if suspended else 'resume'}").raise_for_status()


def can_query(service_id: str) -> bool:
    if service_id.startswith('fly:'):
        from control import fly
        return fly.api_ready()
    return api_ready()


def deploy_status(service_id: str) -> str:
    """Render-style status of the newest deploy (build_in_progress, update_in_progress, live, ...) for either provider."""
    if service_id.startswith('fly:'):
        from control import fly
        return fly.deploy_status(service_id[4:])
    with _client() as c:
        r = c.get(f'/services/{service_id}/deploys', params={'limit': 1})
        r.raise_for_status()
        items = r.json()
    if not items:
        return 'created'
    item = items[0]
    return str((item.get('deploy') or item).get('status') or 'unknown')
