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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

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
]


def _pg_url() -> str:
    return os.getenv('DATABASE_URL', '').strip()


def q(sql: str, args: tuple = (), fetch: bool = False) -> list[dict]:
    """Run one statement on Postgres (DATABASE_URL) or the local SQLite file; '?' placeholders."""
    if _pg_url():
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(_pg_url(), connect_timeout=10, row_factory=dict_row) as con:
            for s in SCHEMAS:
                con.execute(s.format(pk='BIGSERIAL PRIMARY KEY'))
            cur = con.execute(sql.replace('?', '%s'), args)
            return list(cur.fetchall()) if fetch else []
    with closing(sqlite3.connect(db_path())) as con, con:
        con.row_factory = sqlite3.Row
        for s in SCHEMAS:
            con.execute(s.format(pk='INTEGER PRIMARY KEY'))
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
         '<meta name="twitter:image" content="{{ORIGIN}}/assets/og.png"><link rel="icon" type="image/svg+xml" href="/assets/icon.svg">')


def page(name: str) -> HTMLResponse:
    origin = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    html = (STATIC / name).read_text(encoding='utf-8').replace('</head>', SHARE + '</head>', 1)
    return HTMLResponse(html.replace('{{ORIGIN}}', origin).replace('{{BRAND}}', BRAND))


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


@app.get('/zaloguj')
def login_page():
    return page('login.html')


@app.get('/rejestracja')
def register_page():
    return page('register.html')


@app.get('/konto')
def account_page(request: Request):
    if not current_account(request):
        return RedirectResponse('/zaloguj', 303)
    return page('account.html')


@app.get('/konto/panel')
def open_panel(request: Request):
    acc = current_account(request)
    if not acc:
        return RedirectResponse('/zaloguj', 303)
    if acc['status'] != 'active' or not acc.get('instance_url') or not acc.get('sso_secret'):
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
async def register(request: Request):
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
    q('INSERT INTO accounts(email,name,pw_hash,status,mode,consent_marketing,created) VALUES(?,?,?,?,?,?,?)',
      (email, str(body.get('name', '')).strip()[:60], hash_password(password), 'pending', mode, int(body.get('marketing') is True), time.time()))
    acc = q('SELECT id FROM accounts WHERE email=?', (email,), fetch=True)[0]
    return _cookie(JSONResponse({'ok': True}), new_session(acc['id']))


@app.post('/api/login')
async def login(request: Request):
    body = await _json(request)
    email = str(body.get('email', '')).strip().lower()
    if _limited('login:' + _client_ip(request), 20) or _limited('login:' + email, 10):
        raise HTTPException(429, 'Za dużo prób logowania. Spróbuj za godzinę.')
    rows = q('SELECT id,pw_hash,status FROM accounts WHERE email=?', (email,), fetch=True)
    if not rows or not check_password(str(body.get('password', '')), rows[0]['pw_hash']) or rows[0]['status'] == 'disabled':
        raise HTTPException(401, 'Nieprawidłowy e-mail lub hasło.')
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
            'panel_ready': acc['status'] == 'active' and bool(acc.get('instance_url')) and bool(acc.get('sso_secret'))}


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


def _admin(request: Request):
    expected = os.getenv('ADMIN_TOKEN', '')
    supplied = request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    if len(expected) < 24 or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, 'Unauthorized')


@app.get('/admin/accounts')
def admin_accounts(request: Request):
    _admin(request)
    rows = q('SELECT email,name,status,instance_url,mode,consent_marketing,created FROM accounts ORDER BY created DESC', fetch=True)
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
    q("UPDATE accounts SET status='active', instance_url=?, sso_secret=? WHERE email=?", (url, secret, email))
    return {'email': email, 'instance_url': url, 'sso_secret': secret}


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
