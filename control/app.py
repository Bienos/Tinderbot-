"""Control plane: public landing page and beta waitlist (payments come later).

Runs as its own small service, separate from customer instances. Stores only what a visitor submits
(email, optional first name, preferred mode, consents) in its own SQLite file.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from control import mailer, provision

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
BRAND = os.getenv('BRAND_NAME', 'Iskra')
EMAIL = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$')
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'; object-src 'none'")
_HITS: dict[str, list[float]] = {}

app = FastAPI(title=f'{BRAND} control', docs_url=None, redoc_url=None, openapi_url=None)


def db_path() -> Path:
    return Path(os.getenv('CONTROL_DB_PATH', str(BASE / 'control.db')))


SCHEMAS = [
    'CREATE TABLE IF NOT EXISTS waitlist (id {pk}, email TEXT UNIQUE NOT NULL, name TEXT, mode TEXT NOT NULL, '
    'created DOUBLE PRECISION NOT NULL, consent_terms INTEGER NOT NULL, consent_marketing INTEGER NOT NULL)',
    'CREATE TABLE IF NOT EXISTS accounts (id {pk}, email TEXT UNIQUE NOT NULL, name TEXT, pw_hash TEXT NOT NULL, '
    "status TEXT NOT NULL DEFAULT 'pending', instance_url TEXT, sso_secret TEXT, mode TEXT, consent_marketing INTEGER NOT NULL DEFAULT 0, "
    'created DOUBLE PRECISION NOT NULL)',
    'CREATE TABLE IF NOT EXISTS account_sessions (id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, expires DOUBLE PRECISION NOT NULL)',
    'CREATE TABLE IF NOT EXISTS password_resets (id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, expires DOUBLE PRECISION NOT NULL)',
]


MIGRATIONS = [('accounts', 'stripe_customer', 'TEXT'), ('accounts', 'plan_status', "TEXT NOT NULL DEFAULT 'none'"),
              ('accounts', 'comped', 'INTEGER NOT NULL DEFAULT 0'), ('accounts', 'render_service_id', 'TEXT'),
              ('accounts', 'provision_state', 'TEXT'), ('accounts', 'provision_error', 'TEXT'),
              ('accounts', 'start_consent_at', 'DOUBLE PRECISION'), ('accounts', 'paid_at', 'DOUBLE PRECISION'),
              ('accounts', 'withdrawn_at', 'DOUBLE PRECISION'), ('accounts', 'provision_started', 'DOUBLE PRECISION')]
WITHDRAWAL_DAYS = 14


def _pg_url() -> str:
    return os.getenv('DATABASE_URL', '').strip()


def q(sql: str, args: tuple = (), fetch: bool = False) -> list[dict]:
    """Run one statement on Postgres (DATABASE_URL) or the local SQLite file; '?' placeholders."""
    if _pg_url():
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(_pg_url(), connect_timeout=10, row_factory=dict_row, autocommit=True) as con:
            for s in SCHEMAS:
                con.execute(s.format(pk='BIGSERIAL PRIMARY KEY'))
            for table, col, typ in MIGRATIONS:
                con.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}')
            cur = con.execute(sql.replace('?', '%s'), args)
            return list(cur.fetchall()) if fetch else []
    with closing(sqlite3.connect(db_path())) as con, con:
        con.row_factory = sqlite3.Row
        for s in SCHEMAS:
            con.execute(s.format(pk='INTEGER PRIMARY KEY'))
        for table, col, typ in MIGRATIONS:
            if col not in {r[1] for r in con.execute(f'PRAGMA table_info({table})')}:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
        cur = con.execute(sql, args)
        return [dict(r) for r in cur.fetchall()] if fetch else []


def save_signup(email: str, name: str, mode: str, marketing: bool) -> None:
    q('INSERT INTO waitlist(email,name,mode,created,consent_terms,consent_marketing) VALUES(?,?,?,?,1,?) '
      'ON CONFLICT(email) DO UPDATE SET name=excluded.name, mode=excluded.mode, consent_marketing=excluded.consent_marketing',
      (email, name, mode, time.time(), int(marketing)))


def list_signups() -> list[dict]:
    return q('SELECT email,name,mode,created,consent_marketing FROM waitlist ORDER BY created DESC', fetch=True)


# ---- passwords, sessions, single sign-on to the customer's own instance
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return 'scrypt$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split('$')
        test = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(test, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _sid(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_session(account_id: int) -> str:
    raw = secrets.token_urlsafe(32)
    q('DELETE FROM account_sessions WHERE expires<?', (time.time(),))
    q('INSERT INTO account_sessions VALUES(?,?,?)', (_sid(raw), account_id, time.time() + 14 * 86400))
    return raw


def current_account(request: Request) -> dict | None:
    raw = request.cookies.get('iskra_session', '')
    if not raw or len(raw) > 100:
        return None
    rows = q('SELECT a.* FROM account_sessions s JOIN accounts a ON a.id=s.account_id WHERE s.id=? AND s.expires>?',
             (_sid(raw), time.time()), fetch=True)
    return rows[0] if rows else None


def sso_token(account: dict) -> str:
    """Single-use, 60-second sign-in link for the customer's own instance, HMAC-signed with its secret."""
    origin = account['instance_url'].rstrip('/')
    payload = base64.urlsafe_b64encode(json.dumps({'aud': origin, 'sub': account['email'], 'exp': int(time.time()) + 60,
                                                   'n': secrets.token_urlsafe(16)}, separators=(',', ':')).encode()).decode().rstrip('=')
    sig = hmac.new(account['sso_secret'].encode(), payload.encode(), hashlib.sha256).digest()
    return payload + '.' + base64.urlsafe_b64encode(sig).decode().rstrip('=')


def _cookie(response, raw: str | None):
    secure = os.getenv('PUBLIC_ORIGIN', '').startswith('https://')
    if raw is None:
        response.delete_cookie('iskra_session', path='/')
    else:
        response.set_cookie('iskra_session', raw, httponly=True, secure=secure, samesite='lax', max_age=14 * 86400, path='/')
    return response


def _same_origin(request: Request):
    origin = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    if origin and request.headers.get('origin', '').rstrip('/') != origin:
        raise HTTPException(403, 'Nieprawidłowe źródło żądania.')


async def _json(request: Request) -> dict:
    _same_origin(request)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, 'Nieprawidłowe dane')
    if not isinstance(body, dict):
        raise HTTPException(422, 'Nieprawidłowe dane')
    return body


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff',
                             'Referrer-Policy': 'strict-origin-when-cross-origin', 'X-Frame-Options': 'DENY'})
    if os.getenv('PUBLIC_ORIGIN', '').startswith('https://'):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


SHARE = ('<meta property="og:type" content="website"><meta property="og:site_name" content="{{BRAND}}">'
         '<meta property="og:title" content="{{BRAND}}: zamień dopasowania w spotkania">'
         '<meta property="og:description" content="Asystent randkowy AI, który pisze Twoim stylem, wyczuwa moment na zaproszenie i pilnuje, żeby żadna dobra rozmowa nie zgasła.">'
         '<meta property="og:url" content="{{ORIGIN}}/"><meta property="og:image" content="{{ORIGIN}}/assets/og.png">'
         '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
         '<meta property="og:image:alt" content="Iskra: wiadomość, sygnały, szkic odpowiedzi i umówiona kawa">'
         '<meta property="og:locale" content="pl_PL"><meta name="twitter:card" content="summary_large_image">'
         '<meta name="twitter:title" content="{{BRAND}}: zamień dopasowania w spotkania">'
         '<meta name="twitter:description" content="Asystent randkowy AI, który pisze Twoim stylem i wie, kiedy zaprosić.">'
         '<meta name="twitter:image" content="{{ORIGIN}}/assets/og.png"><link rel="icon" type="image/svg+xml" href="/assets/icon.svg"><link rel="apple-touch-icon" href="/apple-touch-icon.png">')


ASSET_VERSIONS = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:10]
                  for path in STATIC.iterdir() if path.suffix in {'.css', '.js'} or path.name == 'icon.svg'}


def versioned_assets(html: str) -> str:
    """Asset URLs carry a content hash so a cached stylesheet never outlives a deploy."""
    def stamp(match: re.Match) -> str:
        version = ASSET_VERSIONS.get(match.group(1))
        return f'/assets/{match.group(1)}?v={version}' if version else match.group(0)
    return re.sub(r'/assets/([A-Za-z0-9_.-]+)', stamp, html)


def page(name: str) -> HTMLResponse:
    origin = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    html = (STATIC / name).read_text(encoding='utf-8').replace('</head>', SHARE + '</head>', 1)
    price = os.getenv('PLAN_PRICE', '').strip() or 'cena widoczna przy płatności'
    for key, fallback in LEGAL_FIELDS.items():
        html = html.replace('{{' + key + '}}', os.getenv(key, '').strip() or fallback)
    html = html.replace('{{ORIGIN}}', origin).replace('{{PRICE}}', price).replace('{{BRAND}}', BRAND)
    return HTMLResponse(versioned_assets(html), headers={'Cache-Control': 'no-cache'})


# Seller identity required by art. 8 of the e-services act and art. 12 of the consumer-rights act.
LEGAL_FIELDS = {'LEGAL_NAME': '[imię i nazwisko lub firma]', 'LEGAL_ADDRESS': '[adres]',
                'LEGAL_ID': '[NIP albo „działalność nierejestrowana”]', 'LEGAL_EMAIL': 'kontakt@iskra.example'}


@app.get('/')
def landing():
    return page('index.html')


@app.get('/prywatnosc')
def privacy():
    return page('privacy.html')


@app.get('/regulamin')
def terms():
    return page('terms.html')


@app.get('/assets/{name}')
def asset(name: str):
    types = {'landing.js': 'text/javascript', 'account.js': 'text/javascript', 'landing.css': 'text/css',
             'og.png': 'image/png', 'icon.svg': 'image/svg+xml'}
    if name not in types:
        raise HTTPException(404)
    return FileResponse(STATIC / name, media_type=types[name], headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/apple-touch-icon.png')
@app.get('/apple-touch-icon-precomposed.png')
def touch_icon():
    return FileResponse(STATIC / 'apple-touch-icon.png', media_type='image/png', headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/zaloguj')
def login_page():
    return page('login.html')


@app.get('/rejestracja')
def register_page():
    return page('register.html')


@app.get('/nie-pamietam-hasla')
def forgot_page():
    return page('forgot.html')


@app.get('/nowe-haslo')
def reset_page():
    return page('reset.html')


@app.get('/konto')
def account_page(request: Request):
    if not current_account(request):
        return RedirectResponse('/zaloguj', 303)
    return page('account.html')


@app.get('/konto/zaawansowane')
def account_advanced_page(request: Request):
    """Account deletion lives here, linked only from the panel's Settings → Account tab, not from the main account page."""
    if not current_account(request):
        return RedirectResponse('/zaloguj', 303)
    return page('account_advanced.html')


@app.get('/konto/panel')
def open_panel(request: Request):
    acc = current_account(request)
    if not acc:
        return RedirectResponse('/zaloguj', 303)
    if acc['status'] != 'active' or not acc.get('instance_url') or not acc.get('sso_secret') or not has_access(acc):
        return RedirectResponse('/konto', 303)
    return RedirectResponse(acc['instance_url'].rstrip('/') + '/auth/sso?t=' + sso_token(acc), 303)


@app.get('/health')
def health():
    return {'status': 'ok'}


def _rate_limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _HITS.get(ip, []) if t > now - 3600]
    _HITS[ip] = hits + [now]
    return len(hits) >= 5


@app.post('/api/waitlist')
async def waitlist(request: Request):
    ip = request.client.host if request.client else '?'
    if os.getenv('TRUST_PROXY') == 'true':  # behind Render's proxy: the left-most forwarded address is the visitor
        ip = request.headers.get('x-forwarded-for', ip).split(',')[0].strip() or ip
    if _rate_limited(ip):
        raise HTTPException(429, 'Za dużo zgłoszeń z tego adresu. Spróbuj za godzinę.')
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, 'Nieprawidłowe dane')
    if not isinstance(body, dict):
        raise HTTPException(422, 'Nieprawidłowe dane')
    if body.get('website'):  # honeypot field, invisible to people
        return {'ok': True}
    email = str(body.get('email', '')).strip().lower()
    name = str(body.get('name', '')).strip()[:60]
    mode = body.get('mode') if body.get('mode') in ('drafts', 'autopilot', 'unsure') else 'unsure'
    if not EMAIL.match(email):
        raise HTTPException(422, 'Podaj poprawny adres e-mail.')
    if body.get('adult') is not True or body.get('terms') is not True:
        raise HTTPException(422, 'Potwierdź, że masz 18 lat i akceptujesz regulamin oraz politykę prywatności.')
    save_signup(email, name, mode, body.get('marketing') is True)
    return {'ok': True}


def _limited(key: str, limit: int) -> bool:
    now = time.time()
    hits = [t for t in _HITS.get(key, []) if t > now - 3600]
    _HITS[key] = hits + [now]
    return len(hits) >= limit


def _client_ip(request: Request) -> str:
    ip = request.client.host if request.client else '?'
    if os.getenv('TRUST_PROXY') == 'true':
        ip = request.headers.get('x-forwarded-for', ip).split(',')[0].strip() or ip
    return ip


@app.post('/api/register')
async def register(request: Request, tasks: BackgroundTasks):
    body = await _json(request)
    if _limited('reg:' + _client_ip(request), 5):
        raise HTTPException(429, 'Za dużo prób. Spróbuj za godzinę.')
    if body.get('website'):
        return {'ok': True}
    email = str(body.get('email', '')).strip().lower()
    password = str(body.get('password', ''))
    if not EMAIL.match(email):
        raise HTTPException(422, 'Podaj poprawny adres e-mail.')
    if not 10 <= len(password) <= 200:
        raise HTTPException(422, 'Hasło musi mieć co najmniej 10 znaków.')
    if body.get('adult') is not True or body.get('terms') is not True:
        raise HTTPException(422, 'Potwierdź, że masz 18 lat i akceptujesz regulamin oraz politykę prywatności.')
    if q('SELECT 1 FROM accounts WHERE email=?', (email,), fetch=True):
        raise HTTPException(409, 'Konto z tym adresem już istnieje. Zaloguj się.')
    mode = body.get('mode') if body.get('mode') in ('drafts', 'autopilot', 'unsure') else 'unsure'
    comped = is_owner(email) or email in {e.strip().lower() for e in os.getenv('COMPED_EMAILS', '').split(',') if e.strip()}
    q('INSERT INTO accounts(email,name,pw_hash,status,mode,consent_marketing,created,comped) VALUES(?,?,?,?,?,?,?,?)',
      (email, str(body.get('name', '')).strip()[:60], hash_password(password), 'pending', mode, int(body.get('marketing') is True), time.time(), int(comped)))
    acc = q('SELECT id FROM accounts WHERE email=?', (email,), fetch=True)[0]
    tasks.add_task(mailer.welcome, email, _origin(request))
    if is_owner(email):
        tasks.add_task(run_provision, acc['id'], _origin(request))
    return _cookie(JSONResponse({'ok': True}), new_session(acc['id']))


@app.post('/api/login')
async def login(request: Request, tasks: BackgroundTasks):
    body = await _json(request)
    email = str(body.get('email', '')).strip().lower()
    if _limited('login:' + _client_ip(request), 20) or _limited('login:' + email, 10):
        raise HTTPException(429, 'Za dużo prób logowania. Spróbuj za godzinę.')
    rows = q('SELECT id,pw_hash,status,instance_url,provision_state FROM accounts WHERE email=?', (email,), fetch=True)
    if not rows or not check_password(str(body.get('password', '')), rows[0]['pw_hash']) or rows[0]['status'] == 'disabled':
        raise HTTPException(401, 'Nieprawidłowy e-mail lub hasło.')
    if is_owner(email) and not rows[0].get('instance_url') and rows[0].get('provision_state') != 'running':
        tasks.add_task(run_provision, rows[0]['id'], _origin(request))  # owner registered before provisioning was set up
    return _cookie(JSONResponse({'ok': True}), new_session(rows[0]['id']))


@app.post('/api/logout')
async def logout(request: Request):
    _same_origin(request)
    raw = request.cookies.get('iskra_session', '')
    if raw:
        q('DELETE FROM account_sessions WHERE id=?', (_sid(raw),))
    return _cookie(JSONResponse({'ok': True}), None)


@app.get('/api/me')
def me(request: Request):
    acc = current_account(request)
    if not acc:
        raise HTTPException(401, 'Nie jesteś zalogowany.')
    return {'email': acc['email'], 'name': acc.get('name') or '', 'status': acc['status'],
            'billing_enabled': billing_enabled(), 'plan_status': acc.get('plan_status') or 'none', 'has_access': has_access(acc),
            'can_manage_billing': billing_enabled() and bool(acc.get('stripe_customer')),
            'provision_state': acc.get('provision_state') or '', 'can_withdraw': can_withdraw(acc),
            'withdrawn': bool(acc.get('withdrawn_at')),
            'panel_ready': acc['status'] == 'active' and bool(acc.get('instance_url')) and bool(acc.get('sso_secret')) and has_access(acc),
            'setup': setup_progress(acc)}


SETUP_SECONDS = {'create': 240, 'link': 120}  # typical time from start to a live server
_DEPLOY_CACHE: dict[str, tuple[float, str]] = {}
BUILDING = {'created', 'queued', 'build_in_progress'}
STARTING = {'update_in_progress', 'pre_deploy_in_progress'}
BROKEN = {'build_failed', 'update_failed', 'pre_deploy_failed', 'canceled'}


def _deploy_status(service_id: str) -> str:
    """Newest deploy status of the instance, cached for a few seconds so polling pages don't hammer Render."""
    now = time.time()
    cached = _DEPLOY_CACHE.get(service_id)
    if cached and now - cached[0] < 6:
        return cached[1]
    try:
        status = provision.deploy_status(service_id) if provision.api_ready() else 'unknown'
    except Exception:
        status = 'unknown'
    _DEPLOY_CACHE[service_id] = (now, status)
    return status


def setup_progress(acc: dict) -> dict:
    """Where the customer's server is: queued, creating, building, starting, ready (or slow/manual)."""
    owner = is_owner(acc.get('email', ''))
    kind = 'link' if owner else 'create'
    started = acc.get('provision_started')
    state = acc.get('provision_state') or ''
    out = {'kind': kind, 'expected': SETUP_SECONDS[kind], 'elapsed': int(time.time() - started) if started else 0}
    if state == 'failed':
        return {**out, 'stage': 'slow'}
    if state == 'manual':
        return {**out, 'stage': 'manual'}
    if state == 'running':
        return {**out, 'stage': 'creating'}
    if not acc.get('instance_url'):
        return {**out, 'stage': 'queued'}
    service_id = acc.get('render_service_id') or (os.getenv('OWNER_SERVICE_ID', '').strip() if owner else '')
    status = _deploy_status(service_id) if service_id and started and time.time() - started < 3600 else 'live'
    if status in BUILDING:
        return {**out, 'stage': 'building'}
    if status in STARTING:
        return {**out, 'stage': 'starting'}
    if status in BROKEN:
        return {**out, 'stage': 'slow'}
    return {**out, 'stage': 'ready'}


@app.post('/api/account/delete')
async def delete_account(request: Request):
    body = await _json(request)
    acc = current_account(request)
    if not acc:
        raise HTTPException(401, 'Nie jesteś zalogowany.')
    if not check_password(str(body.get('password', '')), acc['pw_hash']):
        raise HTTPException(401, 'Nieprawidłowe hasło.')
    q('DELETE FROM account_sessions WHERE account_id=?', (acc['id'],))
    q('DELETE FROM accounts WHERE id=?', (acc['id'],))
    return _cookie(JSONResponse({'deleted': True}), None)


# ---- billing (Stripe Checkout + webhook + customer portal)
def link_mode() -> bool:
    """Payment Link mode: no Stripe secret key on this server at all; payments are confirmed only by the signed webhook."""
    return bool(os.getenv('STRIPE_PAYMENT_LINK', '').startswith('https://')) and bool(os.getenv('STRIPE_WEBHOOK_SECRET'))


def billing_enabled() -> bool:
    return link_mode() or all(os.getenv(k) for k in ('STRIPE_SECRET_KEY', 'STRIPE_PRICE_ID', 'STRIPE_WEBHOOK_SECRET'))


def can_withdraw(acc: dict) -> bool:
    paid = acc.get('paid_at')
    return bool(paid) and not acc.get('withdrawn_at') and not acc.get('comped') and time.time() - float(paid) <= WITHDRAWAL_DAYS * 86400


def has_access(acc: dict) -> bool:
    return bool(acc.get('comped')) or not billing_enabled() or acc.get('plan_status') in ('active', 'trialing')


def _origin(request: Request) -> str:
    return os.getenv('PUBLIC_ORIGIN', '').rstrip('/') or str(request.base_url).rstrip('/')


@app.post('/api/billing/checkout')
async def billing_checkout(request: Request):
    _same_origin(request)
    acc = current_account(request)
    if not acc:
        raise HTTPException(401, 'Nie jesteś zalogowany.')
    if not billing_enabled():
        raise HTTPException(503, 'Płatności nie są jeszcze włączone.')
    if acc.get('plan_status') in ('active', 'trialing'):
        raise HTTPException(409, 'Masz już aktywną subskrypcję.')
    body = await _json(request)
    if body.get('start_now') is not True:
        raise HTTPException(422, 'Zaznacz zgodę na rozpoczęcie usługi przed upływem 14 dni i akceptację regulaminu.')
    q('UPDATE accounts SET start_consent_at=? WHERE id=?', (time.time(), acc['id']))
    if link_mode():
        from urllib.parse import urlencode
        return {'url': os.environ['STRIPE_PAYMENT_LINK'] + '?' + urlencode({'client_reference_id': str(acc['id']), 'prefilled_email': acc['email'], 'locale': 'pl'})}
    import stripe
    params = dict(mode='subscription', line_items=[{'price': os.environ['STRIPE_PRICE_ID'], 'quantity': 1}],
                  client_reference_id=str(acc['id']), success_url=_origin(request) + '/konto?platnosc=ok',
                  cancel_url=_origin(request) + '/konto', allow_promotion_codes=True, locale='pl',
                  metadata={'account_id': str(acc['id'])}, subscription_data={'metadata': {'account_id': str(acc['id'])}},
                  custom_text={'submit': {'message': 'Zamawiając, prosisz o rozpoczęcie usługi przed upływem 14 dni na odstąpienie od umowy.'}})
    if acc.get('stripe_customer'):
        params['customer'] = acc['stripe_customer']
    else:
        params['customer_email'] = acc['email']
    session = stripe.checkout.Session.create(api_key=os.environ['STRIPE_SECRET_KEY'], **params)
    return {'url': session.url}


@app.post('/api/billing/withdraw')
async def billing_withdraw(request: Request, tasks: BackgroundTasks):
    """Consumer withdrawal within 14 days (art. 27 consumer-rights act), one click plus confirmation, no reason needed."""
    _same_origin(request)
    acc = current_account(request)
    if not acc:
        raise HTTPException(401, 'Nie jesteś zalogowany.')
    if (await _json(request)).get('confirm') is not True:
        raise HTTPException(422, 'Potwierdź odstąpienie od umowy.')
    if not can_withdraw(acc):
        raise HTTPException(409, 'Termin 14 dni na odstąpienie minął albo umowa nie została jeszcze zawarta. '
                                 'Subskrypcję możesz anulować w „Zarządzaj subskrypcją”.')
    now = time.time()
    q("UPDATE accounts SET withdrawn_at=?, plan_status='withdrawn' WHERE id=?", (now, acc['id']))
    if acc.get('render_service_id') and provision.enabled():
        tasks.add_task(_safe_suspend, acc['render_service_id'])
    tasks.add_task(mailer.withdrawal_confirmed, acc['email'], _origin(request))
    owner = os.getenv('LEGAL_EMAIL', '').strip() or os.getenv('OWNER_EMAIL', '').strip()
    if owner:
        tasks.add_task(mailer.safe_send, owner, f'Odstąpienie od umowy: konto {acc["id"]}',
                       f'Klient {acc["email"]} odstąpił od umowy. Anuluj subskrypcję w Stripe (klient {acc.get("stripe_customer")}) '
                       f'i zwróć kwotę pomniejszoną o dni korzystania w ciągu 14 dni.')
    return {'withdrawn': True}


def _safe_suspend(service_id: str) -> None:
    try:
        provision.set_suspended(service_id, True)
    except Exception:
        pass


@app.post('/api/billing/portal')
async def billing_portal(request: Request):
    _same_origin(request)
    acc = current_account(request)
    if not acc:
        raise HTTPException(401, 'Nie jesteś zalogowany.')
    if not billing_enabled() or not acc.get('stripe_customer'):
        raise HTTPException(409, 'Brak subskrypcji do zarządzania.')
    if link_mode():
        portal = os.getenv('STRIPE_PORTAL_URL', '')
        if not portal.startswith('https://'):
            raise HTTPException(503, 'Portal płatności nie jest jeszcze skonfigurowany.')
        from urllib.parse import urlencode
        return {'url': portal + '?' + urlencode({'prefilled_email': acc['email']})}
    import stripe
    session = stripe.billing_portal.Session.create(api_key=os.environ['STRIPE_SECRET_KEY'], customer=acc['stripe_customer'],
                                                   return_url=_origin(request) + '/konto')
    return {'url': session.url}


@app.post('/stripe/webhook')
async def stripe_webhook(request: Request, tasks: BackgroundTasks):
    """Stripe tells us about payments. The signature is verified with STRIPE_WEBHOOK_SECRET; nothing else is trusted."""
    import stripe
    secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
    if not secret:
        raise HTTPException(503, 'Webhook not configured')
    payload = await request.body()
    try:
        stripe.Webhook.construct_event(payload, request.headers.get('stripe-signature', ''), secret)  # verifies signature + age
        event = json.loads(payload)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, 'Invalid signature')
    obj = event.get('data', {}).get('object', {})
    if event['type'] == 'checkout.session.completed' and obj.get('mode') == 'subscription':
        ref = str(obj.get('client_reference_id') or '')
        if ref.isdigit():
            q("UPDATE accounts SET stripe_customer=?, plan_status='active', withdrawn_at=NULL, paid_at=COALESCE(paid_at, ?) WHERE id=?",
              (obj.get('customer'), time.time(), int(ref)))
            rows = q('SELECT email FROM accounts WHERE id=?', (int(ref),), fetch=True)
            if rows:
                tasks.add_task(mailer.payment_ok, rows[0]['email'], _origin(request))
                tasks.add_task(run_provision, int(ref), _origin(request))
    elif event['type'] in ('customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted'):
        status = 'canceled' if event['type'] == 'customer.subscription.deleted' else str(obj.get('status', 'none'))
        # A withdrawn contract stays withdrawn until the owner cancels it in Stripe; only a fresh checkout reopens it.
        q('UPDATE accounts SET plan_status=? WHERE stripe_customer=? AND withdrawn_at IS NULL', (status[:30], obj.get('customer')))
        for acc in q('SELECT render_service_id FROM accounts WHERE stripe_customer=? AND render_service_id IS NOT NULL', (obj.get('customer'),), fetch=True):
            if provision.enabled():
                tasks.add_task(_suspend, acc['render_service_id'], status not in ('active', 'trialing'))
    return {'received': True}


def run_provision(account_id: int, origin: str = '') -> str:
    """Create the customer's instance once. Safe to call again: it skips accounts that already have one."""
    rows = q('SELECT * FROM accounts WHERE id=?', (account_id,), fetch=True)
    if not rows:
        return 'missing'
    acc = rows[0]
    if acc.get('render_service_id') or acc.get('instance_url'):
        return 'exists'
    if is_owner(acc['email']):
        return link_owner(acc)
    if not provision.enabled():
        q("UPDATE accounts SET provision_state='manual' WHERE id=?", (account_id,))
        return 'manual'
    if acc.get('provision_state') == 'running':
        return 'running'
    q("UPDATE accounts SET provision_state='running', provision_error=NULL, provision_started=? WHERE id=?", (time.time(), account_id))
    try:
        inst = provision.create_instance(account_id)
    except Exception as exc:
        q("UPDATE accounts SET provision_state='failed', provision_error=? WHERE id=?", (type(exc).__name__ + ': ' + str(exc)[:240], account_id))
        return 'failed'
    q("UPDATE accounts SET status='active', instance_url=?, sso_secret=?, render_service_id=?, provision_state='done' WHERE id=?",
      (inst['url'], inst['sso_secret'], inst['service_id'], account_id))
    mailer.panel_ready(acc['email'], origin or os.getenv('PUBLIC_ORIGIN', '').rstrip('/'))
    return 'done'


def is_owner(email: str) -> bool:
    return bool(email) and email.lower() == os.getenv('OWNER_EMAIL', '').strip().lower()


def link_owner(acc: dict) -> str:
    """The owner's account uses the bot that already runs (OWNER_SERVICE_ID): free, linked by single sign-on."""
    sid = os.getenv('OWNER_SERVICE_ID', '').strip()
    if not sid or not provision.api_ready():
        q("UPDATE accounts SET comped=1, provision_state='manual' WHERE id=?", (acc['id'],))
        return 'manual'
    q('UPDATE accounts SET provision_started=? WHERE id=?', (time.time(), acc['id']))
    try:
        inst = provision.link_existing(sid)
    except Exception as exc:
        q("UPDATE accounts SET comped=1, provision_state='failed', provision_error=? WHERE id=?", (type(exc).__name__ + ': ' + str(exc)[:240], acc['id']))
        return 'failed'
    q("UPDATE accounts SET status='active', comped=1, instance_url=?, sso_secret=?, provision_state='done' WHERE id=?",
      (inst['url'], inst['sso_secret'], acc['id']))
    return 'done'


def _suspend(service_id: str, suspended: bool) -> None:
    try:
        provision.set_suspended(service_id, suspended)
    except Exception:
        pass


# ---- password reset
@app.post('/api/password/forgot')
async def password_forgot(request: Request, tasks: BackgroundTasks):
    body = await _json(request)
    email = str(body.get('email', '')).strip().lower()
    if _limited('forgot:' + _client_ip(request), 5) or _limited('forgot:' + email, 3):
        raise HTTPException(429, 'Za dużo prób. Spróbuj za godzinę.')
    rows = q('SELECT id FROM accounts WHERE email=?', (email,), fetch=True)
    if rows:
        raw = secrets.token_urlsafe(32)
        q('DELETE FROM password_resets WHERE account_id=? OR expires<?', (rows[0]['id'], time.time()))
        q('INSERT INTO password_resets VALUES(?,?,?)', (_sid(raw), rows[0]['id'], time.time() + 3600))
        tasks.add_task(mailer.password_reset, email, _origin(request) + '/nowe-haslo?t=' + raw)
    return {'ok': True}  # same answer either way, so the form does not reveal who has an account


@app.post('/api/password/reset')
async def password_reset(request: Request):
    body = await _json(request)
    raw, password = str(body.get('token', '')), str(body.get('password', ''))
    if not 10 <= len(password) <= 200:
        raise HTTPException(422, 'Hasło musi mieć co najmniej 10 znaków.')
    rows = q('SELECT account_id FROM password_resets WHERE id=? AND expires>?', (_sid(raw), time.time()), fetch=True) if raw else []
    if not rows:
        raise HTTPException(400, 'Link wygasł albo był już użyty. Poproś o nowy.')
    aid = rows[0]['account_id']
    q('UPDATE accounts SET pw_hash=? WHERE id=?', (hash_password(password), aid))
    q('DELETE FROM password_resets WHERE account_id=?', (aid,))
    q('DELETE FROM account_sessions WHERE account_id=?', (aid,))
    return _cookie(JSONResponse({'ok': True}), new_session(aid))


def _admin(request: Request):
    expected = os.getenv('ADMIN_TOKEN', '')
    supplied = request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    if len(expected) < 24 or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, 'Unauthorized')


@app.get('/admin/accounts')
def admin_accounts(request: Request):
    _admin(request)
    rows = q('SELECT email,name,status,plan_status,comped,instance_url,render_service_id,provision_state,provision_error,mode,consent_marketing,created '
             'FROM accounts ORDER BY created DESC', fetch=True)
    return {'count': len(rows), 'items': rows}


@app.post('/admin/accounts/activate')
async def admin_activate(request: Request):
    """Bind an account to its instance. Returns the SSO secret once: set it as SSO_SECRET on that instance."""
    _admin(request)
    body = await request.json()
    email, url = str(body.get('email', '')).strip().lower(), str(body.get('instance_url', '')).strip().rstrip('/')
    if not re.fullmatch(r'https://[a-z0-9.-]+(:\d+)?', url):
        raise HTTPException(422, 'instance_url must be an https origin')
    if not q('SELECT 1 FROM accounts WHERE email=?', (email,), fetch=True):
        raise HTTPException(404, 'No such account')
    secret = secrets.token_urlsafe(32)
    q("UPDATE accounts SET status='active', instance_url=?, sso_secret=?, comped=? WHERE email=?",
      (url, secret, int(body.get('comped') is True), email))
    return {'email': email, 'instance_url': url, 'sso_secret': secret}


@app.post('/admin/accounts/provision')
async def admin_provision(request: Request):
    _admin(request)
    body = await request.json()
    rows = q('SELECT id FROM accounts WHERE email=?', (str(body.get('email', '')).strip().lower(),), fetch=True)
    if not rows:
        raise HTTPException(404, 'No such account')
    if body.get('retry'):
        q("UPDATE accounts SET provision_state=NULL WHERE id=? AND provision_state IN ('failed','manual')", (rows[0]['id'],))
    return {'result': run_provision(rows[0]['id'], _origin(request))}


@app.post('/admin/accounts/status')
async def admin_status(request: Request):
    _admin(request)
    body = await request.json()
    status = body.get('status')
    if status not in ('pending', 'active', 'disabled'):
        raise HTTPException(422, 'status must be pending, active or disabled')
    q('UPDATE accounts SET status=? WHERE email=?', (status, str(body.get('email', '')).strip().lower()))
    if status == 'disabled':
        q('DELETE FROM account_sessions WHERE account_id IN (SELECT id FROM accounts WHERE email=?)', (str(body.get('email', '')).strip().lower(),))
    return {'ok': True}


@app.get('/admin/waitlist')
def admin_waitlist(request: Request):
    _admin(request)
    rows = list_signups()
    return JSONResponse({'count': len(rows), 'items': rows})
