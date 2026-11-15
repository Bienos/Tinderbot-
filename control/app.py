"""Control plane: public landing page and beta waitlist (payments come later).

Runs as its own small service, separate from customer instances. Stores only what a visitor submits
(email, optional first name, preferred mode, consents) in its own SQLite file.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

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


SCHEMA = ('CREATE TABLE IF NOT EXISTS waitlist (id {pk}, email TEXT UNIQUE NOT NULL, name TEXT, mode TEXT NOT NULL, '
          'created DOUBLE PRECISION NOT NULL, consent_terms INTEGER NOT NULL, consent_marketing INTEGER NOT NULL)')
UPSERT = ('INSERT INTO waitlist(email,name,mode,created,consent_terms,consent_marketing) VALUES({p},{p},{p},{p},1,{p}) '
          'ON CONFLICT(email) DO UPDATE SET name=excluded.name, mode=excluded.mode, consent_marketing=excluded.consent_marketing')
LIST = 'SELECT email,name,mode,created,consent_marketing FROM waitlist ORDER BY created DESC'


def _pg_url() -> str:
    return os.getenv('DATABASE_URL', '').strip()


def save_signup(email: str, name: str, mode: str, marketing: bool) -> None:
    args = (email, name, mode, time.time(), int(marketing))
    if _pg_url():
        import psycopg
        with psycopg.connect(_pg_url(), connect_timeout=10) as con:
            con.execute(SCHEMA.format(pk='BIGSERIAL PRIMARY KEY'))
            con.execute(UPSERT.format(p='%s'), args)
        return
    with closing(sqlite3.connect(db_path())) as con, con:
        con.execute(SCHEMA.format(pk='INTEGER PRIMARY KEY'))
        con.execute(UPSERT.format(p='?'), args)


def list_signups() -> list[dict]:
    keys = ('email', 'name', 'mode', 'created', 'consent_marketing')
    if _pg_url():
        import psycopg
        with psycopg.connect(_pg_url(), connect_timeout=10) as con:
            con.execute(SCHEMA.format(pk='BIGSERIAL PRIMARY KEY'))
            return [dict(zip(keys, r)) for r in con.execute(LIST).fetchall()]
    with closing(sqlite3.connect(db_path())) as con:
        con.execute(SCHEMA.format(pk='INTEGER PRIMARY KEY'))
        return [dict(zip(keys, r)) for r in con.execute(LIST).fetchall()]


@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({'Content-Security-Policy': CSP, 'X-Content-Type-Options': 'nosniff',
                             'Referrer-Policy': 'strict-origin-when-cross-origin', 'X-Frame-Options': 'DENY'})
    if os.getenv('PUBLIC_ORIGIN', '').startswith('https://'):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


def page(name: str) -> HTMLResponse:
    return HTMLResponse((STATIC / name).read_text(encoding='utf-8').replace('{{BRAND}}', BRAND))


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
    if name not in ('landing.js', 'landing.css'):
        raise HTTPException(404)
    return FileResponse(STATIC / name, media_type='text/javascript' if name.endswith('.js') else 'text/css')


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


@app.get('/admin/waitlist')
def admin_waitlist(request: Request):
    expected = os.getenv('ADMIN_TOKEN', '')
    supplied = request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    if len(expected) < 24 or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, 'Unauthorized')
    rows = list_signups()
    return JSONResponse({'count': len(rows), 'items': rows})
