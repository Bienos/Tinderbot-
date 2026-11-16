"""Control plane: public landing page and beta waitlist (payments come later).

Runs as its own small service, separate from customer instances. Stores only what a visitor submits
(email, optional first name, preferred mode, consents) in its own SQLite file.
"""
from __future__ import annotations

import asyncio
import base64
import html as html_lib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, closing
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from control import mailer, provision, catalog, weekly

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
BRAND = os.getenv('BRAND_NAME', 'Winq')
EMAIL = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$')
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'; object-src 'none'")
_HITS: dict[str, list[float]] = {}

log = logging.getLogger('uvicorn.error')


def run_weekly(now: float, **kw) -> list[dict]:
    origin = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    if not origin:
        return [{'result': 'skipped: PUBLIC_ORIGIN is not set'}]
    return weekly.run(q, now, base_for=panel_url, has_access=has_access, origin=origin, **kw)


async def _weekly_loop():
    """Looks for due summaries every half hour. Each pass is cheap when nothing is due; the database claim in weekly.run
    keeps it safe if two processes run it."""
    await asyncio.sleep(90)
    while True:
        try:
            await asyncio.to_thread(remove_pending_instances)  # bots of deleted accounts that could not be removed earlier
            if mailer.configured() and mailer.sender_problem() is None:
                results = await asyncio.to_thread(run_weekly, time.time())
                sent = sum(1 for r in results if r['result'] == 'sent')
                failed = [r['result'] for r in results if r['result'].startswith('failed')]
                if sent or failed:
                    log.info('weekly summaries: %d sent, %d failed %s', sent, len(failed), failed[:3])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error('weekly summary pass failed: %s: %s', type(exc).__name__, str(exc)[:200])
        await asyncio.sleep(1800)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_weekly_loop()) if os.getenv('WEEKLY_SUMMARY', 'true').strip().lower() != 'false' else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=f'{BRAND} control', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


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
    # Bots of deleted accounts that still have to be removed from the hosting provider (retried until it works).
    'CREATE TABLE IF NOT EXISTS instance_removals (service_id TEXT PRIMARY KEY, created DOUBLE PRECISION NOT NULL, '
    'attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)',
]


MIGRATIONS = [('accounts', 'stripe_customer', 'TEXT'), ('accounts', 'plan_status', "TEXT NOT NULL DEFAULT 'none'"),
              ('accounts', 'comped', 'INTEGER NOT NULL DEFAULT 0'), ('accounts', 'render_service_id', 'TEXT'),
              ('accounts', 'provision_state', 'TEXT'), ('accounts', 'provision_error', 'TEXT'),
              ('accounts', 'start_consent_at', 'DOUBLE PRECISION'), ('accounts', 'paid_at', 'DOUBLE PRECISION'),
              ('accounts', 'withdrawn_at', 'DOUBLE PRECISION'), ('accounts', 'provision_started', 'DOUBLE PRECISION'),
              ('accounts', 'source', 'TEXT'), ('accounts', 'plan', 'TEXT'), ('accounts', 'plan_choice', 'TEXT'),
              ('accounts', 'weekly_summary', 'INTEGER NOT NULL DEFAULT 1'), ('accounts', 'weekly_sent_at', 'DOUBLE PRECISION'),
              ('accounts', 'weekly_claim', 'DOUBLE PRECISION'), ('accounts', 'weekly_note', 'TEXT'), ('accounts', 'unsub_token', 'TEXT'),
              ('accounts', 'plan_period', 'TEXT'), ('accounts', 'period_choice', 'TEXT')]
WITHDRAWAL_DAYS = 14
# Optional "Skąd o nas wiesz?" answer on sign-up.
SIGNUP_SOURCES = ('tiktok', 'instagram', 'friend', 'google', 'other')


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


def panel_url(account: dict) -> str:
    """Where this customer's panel lives. The owner's bot runs on Render's own address; OWNER_PANEL_URL puts it on
    the brand's domain (e.g. https://panel.winq.site) without touching the stored address."""
    custom = os.getenv('OWNER_PANEL_URL', '').strip().rstrip('/')
    if custom.startswith('https://') and is_owner(account.get('email', '')):
        return custom
    return account['instance_url'].rstrip('/')


def sso_token(account: dict) -> str:
    """Single-use, 60-second sign-in link for the customer's own instance, HMAC-signed with its secret."""
    origin = panel_url(account)
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


# Paths that must keep answering on the old address: Stripe's webhook, API calls, admin scripts, health checks.
OLD_HOST_EXEMPT = ('/stripe/', '/api/', '/admin/', '/health')


@app.middleware('http')
async def custom_domain_redirect(request: Request, call_next):
    """Once PUBLIC_ORIGIN is a custom domain, Render's own *.onrender.com address sends page visits there."""
    origin = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    render_host = os.getenv('RENDER_EXTERNAL_HOSTNAME', '').strip().lower()
    if (request.method in ('GET', 'HEAD') and render_host and origin.startswith('https://')
            and request.headers.get('host', '').lower() == render_host and urlsplit(origin).netloc.lower() != render_host
            and not request.url.path.startswith(OLD_HOST_EXEMPT)):
        query = '?' + request.url.query if request.url.query else ''
        return RedirectResponse(origin + request.url.path + query, 301)
    return await call_next(request)


SHARE = ('<meta property="og:type" content="website"><meta property="og:site_name" content="{{BRAND}}">'
         '<meta property="og:title" content="{{BRAND}}. Zamień nowe matche w umówione randki">'
         '<meta property="og:description" content="Asystent randkowy AI, który odpisuje Twoim stylem i w dobrym momencie proponuje spotkanie. Ty czekasz na powiadomienie o umówionej randce.">'
         '<meta property="og:url" content="{{ORIGIN}}{{PATH}}"><meta property="og:image" content="{{ORIGIN}}/assets/og.png">'
         '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
         '<meta property="og:image:alt" content="{{BRAND}} w akcji: wiadomość, sygnały, odpowiedź i umówiona kawa">'
         '<meta property="og:locale" content="pl_PL"><meta name="twitter:card" content="summary_large_image">'
         '<meta name="twitter:title" content="{{BRAND}}. Zamień nowe matche w umówione randki">'
         '<meta name="twitter:description" content="Asystent randkowy AI, który pisze Twoim stylem i umawia randki, a Ty czekasz na powiadomienie.">'
         '<meta name="twitter:image" content="{{ORIGIN}}/assets/og.png"><link rel="icon" type="image/svg+xml" href="/assets/icon.svg"><link rel="apple-touch-icon" href="/apple-touch-icon.png">')


ASSET_VERSIONS = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:10]
                  for path in STATIC.iterdir() if path.suffix in {'.css', '.js'} or path.name == 'icon.svg'}


def versioned_assets(html: str) -> str:
    """Asset URLs carry a content hash so a cached stylesheet never outlives a deploy."""
    def stamp(match: re.Match) -> str:
        version = ASSET_VERSIONS.get(match.group(1))
        return f'/assets/{match.group(1)}?v={version}' if version else match.group(0)
    return re.sub(r'/assets/([A-Za-z0-9_.-]+)', stamp, html)


PATHS = {'index.html': '/', 'privacy.html': '/prywatnosc', 'terms.html': '/regulamin', 'login.html': '/zaloguj',
         'register.html': '/rejestracja', 'forgot.html': '/nie-pamietam-hasla', 'reset.html': '/nowe-haslo',
         'account.html': '/konto', 'unsubscribe.html': '/wypisz-sie'}
# Account pages are not worth indexing. They stay crawlable (not in robots.txt) so the noindex is seen.
NOINDEX = {'login.html', 'register.html', 'forgot.html', 'reset.html', 'account.html', 'unsubscribe.html'}
FAQ = re.compile(r'<details><summary>(.*?)</summary><p>(.*?)</p></details>', re.S)


def _text(fragment: str) -> str:
    return re.sub(r'\s+', ' ', html_lib.unescape(re.sub(r'<[^>]+>', '', fragment))).strip()


def structured_data(html: str, origin: str, price: str) -> str:
    """Organization, WebSite, WebApplication (with the real price) and the FAQ exactly as shown on the page.
    No ratings or reviews: there are none yet, and inventing them is against Google's rules."""
    org = {'@type': 'Organization', '@id': origin + '/#org', 'name': BRAND, 'url': origin + '/',
           'logo': origin + '/apple-touch-icon.png'}
    email = os.getenv('LEGAL_EMAIL', '').strip()
    if email:
        org['email'] = email
    graph = [org,
             {'@type': 'WebSite', '@id': origin + '/#website', 'url': origin + '/', 'name': BRAND, 'inLanguage': 'pl-PL',
              'publisher': {'@id': origin + '/#org'}},
             {'@type': 'WebApplication', '@id': origin + '/#app', 'name': BRAND, 'url': origin + '/', 'inLanguage': 'pl-PL',
              'description': 'Asystent randkowy AI, który odpisuje na Tinderze w Twoim stylu, w dobrym momencie proponuje spotkanie i powiadamia, gdy randka jest umówiona. Autopilot albo szkice do zatwierdzenia.',
              'applicationCategory': 'LifestyleApplication', 'operatingSystem': 'Web', 'publisher': {'@id': origin + '/#org'}}]
    cost = re.search(r'(\d+(?:[.,]\d+)?)\s*zł', price)
    if cost:
        amount = '%.2f' % float(cost.group(1).replace(',', '.'))
        graph[2]['offers'] = {'@type': 'Offer', 'price': amount, 'priceCurrency': 'PLN', 'url': origin + '/rejestracja',
                              'availability': 'https://schema.org/InStock',
                              'priceSpecification': {'@type': 'UnitPriceSpecification', 'price': amount, 'priceCurrency': 'PLN',
                                                     'billingDuration': 1, 'unitCode': 'MON'}}
    faq = [{'@type': 'Question', 'name': _text(q), 'acceptedAnswer': {'@type': 'Answer', 'text': _text(ans)}}
           for q, ans in FAQ.findall(html)]
    if faq:
        graph.append({'@type': 'FAQPage', 'mainEntity': faq})
    body = json.dumps({'@context': 'https://schema.org', '@graph': graph}, ensure_ascii=False).replace('</', '<\\/')
    return '<script type="application/ld+json">' + body + '</script>'


def trial_days() -> int:
    """Free days at the start of a subscription (TRIAL_DAYS). 0 means none. The Stripe payment link must carry the same number."""
    try:
        return max(0, min(30, int(os.getenv('TRIAL_DAYS', '0') or 0)))
    except ValueError:
        return 0


def _days(n: int) -> str:
    return f'{n} dzień' if n == 1 else f'{n} dni'


def _zl(x: float) -> str:
    return (f'{x:.2f}'.replace('.', ',') if x != int(x) else str(int(x))) + ' zł'


def _free_label(n: int) -> str:
    return f'{n} miesiąc gratis' if n == 1 else f'{n} miesiące gratis'


def _period_facts(plan: dict, per: dict) -> dict:
    total = catalog.total(plan, per)
    regular = plan['price'] * per['months']
    longer = per['months'] > 1
    return {'per': _zl(total / per['months']), 'was': _zl(plan['price']) if longer else '', 'total': total, 'regular': regular,
            'save': regular - total, 'months': per['months'], 'free': per['free'],
            'badge': '' if not per['free'] else f'{_free_label(per["free"])} · −{_zl(regular - total)}'}


def tiers_html() -> str:
    """The pricing cards on the landing page, generated from the catalog so prices and limits exist in one place.
    With the 6- and 12-month payment links present there is a period switch (pricing.js) that opens on the year."""
    n = trial_days()
    longer = catalog.periods_enabled()
    default = catalog.period('12' if longer else '1')
    cards = []
    for p in catalog.PLANS:
        items = ''.join(f'<li>{html_lib.escape(f)}</li>' for f in p['features'])
        badge = '<span class="tier-badge">Najczęściej wybierany</span>' if p.get('popular') else ''
        facts = {q['key']: _period_facts(p, q) for q in catalog.PERIODS if longer or q['key'] == '1'}
        cur = facts[default['key']]
        data = html_lib.escape(json.dumps(facts, ensure_ascii=False), quote=True)
        cards.append(
            f'<article class="tier{" popular" if p.get("popular") else ""}" data-slug="{p["slug"]}" data-prices="{data}">{badge}<h3>{p["name"]}</h3>'
            f'<p class="tier-pitch">{html_lib.escape(p["pitch"])}</p>'
            f'<div class="tier-pricebox"><p class="tier-price"><b class="js-per">{cur["per"]}</b><span> / mies.</span>'
            f'<s class="tier-was js-was"{"" if cur["was"] else " hidden"}>{cur["was"]}</s></p>'
            f'<p class="tier-save js-save"{"" if cur["badge"] else " hidden"}>{cur["badge"]}</p></div>'
            f'<ul>{items}</ul>'
            f'<a class="btn{"" if p.get("popular") else " ghost"} js-cta" href="/rejestracja?plan={p["slug"]}&amp;period={default["key"]}">'
            f'Wybieram {p["name"]}</a></article>')
    switch = ''
    if longer:
        tabs = ''.join(f'<button type="button" data-period="{q["key"]}" class="{"on" if q["key"] == default["key"] else ""}" aria-pressed="{"true" if q["key"] == default["key"] else "false"}">'
                       f'{q["label"]}{f"<i>{_free_label(q["free"])}</i>" if q["free"] else ""}</button>' for q in catalog.PERIODS)
        switch = ('<p class="period-lead">Im dłużej, tym taniej. <b>Weź rok i trzy miesiące masz gratis.</b></p>'
                  f'<div class="period" role="group" aria-label="Okres rozliczeniowy">{tabs}</div>')
    trial = (f'<b>Pierwsze {_days(n)} w każdym pakiecie za darmo.</b> Kartę podajesz od razu, a jeśli anulujesz przed końcem okresu próbnego, nic nie zapłacisz. ' if n else '')
    note = (f'<div class="tier-info"><p class="tier-trial">{trial}Anulujesz w każdej chwili, a dostęp działa do końca opłaconego okresu.</p>'
            '<details class="tier-active"><summary>Co to znaczy „aktywna rozmowa”?</summary>'
            '<p>Aktywna rozmowa to taka, w której ktoś odpisał Ci w ciągu ostatnich 14 dni. Gdy rozmowa ucichnie, miejsce się zwalnia, '
            'a rozmowy, w których umawiasz spotkanie, nigdy się nie blokują.</p></details></div>')
    return f'<div class="tiers-wrap" data-period="{default["key"]}">{switch}<div class="tiers" role="group" aria-label="Pakiety">' + ''.join(cards) + '</div></div>' + note


def trial_texts() -> dict[str, str]:
    n = trial_days()
    if not n:
        return {'{{TRIAL}}': '', '{{TRIAL_NOTE}}': '', '{{TRIAL_TERMS}}': ''}
    d = _days(n)
    return {'{{TRIAL}}': f'Pierwsze {d} za darmo, potem ',
            '{{TRIAL_NOTE}}': f' Pierwsze {d} są bezpłatne. Kartę podajesz od razu, a jeśli anulujesz przed ich końcem, nic nie zapłacisz.',
            '{{TRIAL_TERMS}}': (f'<li>Pierwsze {d} Subskrypcji są bezpłatne (okres próbny), a umowa zostaje zawarta z chwilą jego rozpoczęcia. '
                                'Do rozpoczęcia okresu próbnego wymagamy podania metody płatności. Jeżeli nie anulujesz Subskrypcji przed jego końcem, '
                                'pierwsza opłata zostanie pobrana automatycznie po jego zakończeniu. Anulowanie w okresie próbnym oznacza, że nic nie zapłacisz.</li>')}


def page(name: str, fill: dict | None = None) -> HTMLResponse:
    origin = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    path = PATHS.get(name, '/')
    html = (STATIC / name).read_text(encoding='utf-8')
    price = os.getenv('PLAN_PRICE', '').strip() or 'cena widoczna przy płatności'
    extra = SHARE
    if name in NOINDEX:
        extra = '<meta name="robots" content="noindex,follow">' + extra
    if origin:
        extra = f'<link rel="canonical" href="{origin}{path}">' + extra
    html = html.replace('</head>', extra + '</head>', 1)
    for key, fallback in LEGAL_FIELDS.items():
        html = html.replace('{{' + key + '}}', os.getenv(key, '').strip() or fallback)
    for token_, text_ in trial_texts().items():
        html = html.replace(token_, text_)
    prices = ', '.join(f'{p["name"]} {p["price"]} zł' for p in catalog.PLANS)
    if catalog.enabled():
        html = re.sub(r'<!--TICKET-->.*?<!--/TICKET-->', '', html, flags=re.S).replace('{{TIERS}}', tiers_html())
        price = f'od {min(p["price"] for p in catalog.PLANS)} zł / mies.'
        faq_price = f'Trzy pakiety: {prices} miesięcznie.' + (' Przy płatności z góry za 6 miesięcy jeden miesiąc jest gratis, a za rok trzy miesiące gratis.' if catalog.periods_enabled() else '')
        terms_price = f'Cena Subskrypcji zależy od wybranego pakietu: {prices} miesięcznie (kwoty brutto)'
        plan_terms = ('<li>Pakiety różnią się liczbą aktywnych rozmów prowadzonych naraz i dostępnością funkcji Autopilot, zgodnie z opisem w cenniku. '
                      'Aktywna rozmowa to rozmowa, w której druga osoba odpisała w ciągu ostatnich 14 dni. Rozmowy, w których ustalany jest termin spotkania, '
                      'nie są blokowane limitem.</li>'
                      + ('<li>Subskrypcja może być opłacana miesięcznie, za 6 miesięcy z góry (płacisz za 5 miesięcy, jeden miesiąc jest bezpłatny) albo za 12 miesięcy z góry '
                         '(płacisz za 9 miesięcy, trzy miesiące są bezpłatne). Odnawia się automatycznie na kolejny wybrany okres, dopóki jej nie anulujesz. Anulowanie zatrzymuje odnowienie, '
                         'a dostęp działa do końca opłaconego okresu.</li>' if catalog.periods_enabled() else ''))
    else:
        html = html.replace('<!--TICKET-->', '').replace('<!--/TICKET-->', '').replace('{{TIERS}}', '')
        faq_price, terms_price, plan_terms = f'Jeden plan w subskrypcji, {price}.', f'Cena Subskrypcji wynosi {price} (kwota brutto)', ''
    for key, value in (fill or {}).items():
        html = html.replace(key, value)
    html = html.replace('{{PRICE_FAQ}}', faq_price).replace('{{PRICE_TERMS}}', terms_price).replace('{{PLAN_TERMS}}', plan_terms)
    html = html.replace('{{ORIGIN}}', origin).replace('{{PATH}}', path).replace('{{PRICE}}', price).replace('{{BRAND}}', BRAND)
    if name == 'index.html' and origin:
        html = html.replace('</head>', structured_data(html, origin, price) + '</head>', 1)
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
             'og.png': 'image/png', 'email-logo.png': 'image/png', 'pricing.js': 'text/javascript', 'icon.svg': 'image/svg+xml'}
    if name not in types:
        raise HTTPException(404)
    return FileResponse(STATIC / name, media_type=types[name], headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/assets/fonts/{name}')
def font(name: str):
    if not re.fullmatch(r'(onest|unbounded)-latin(-ext)?-v1\.woff2', name):
        raise HTTPException(404)
    return FileResponse(STATIC / 'fonts' / name, media_type='font/woff2',
                        headers={'Cache-Control': 'public, max-age=31536000, immutable'})


@app.get('/robots.txt')
def robots(request: Request):
    lines = ['User-agent: *', 'Allow: /', 'Disallow: /api/', 'Disallow: /admin/', 'Disallow: /stripe/', 'Disallow: /konto', '']
    lines.append('Sitemap: ' + _origin(request) + '/sitemap.xml')
    return PlainTextResponse('\n'.join(lines) + '\n', headers={'Cache-Control': 'public, max-age=3600'})


@app.get('/sitemap.xml')
def sitemap(request: Request):
    origin = _origin(request)
    urls = ''.join(f'<url><loc>{origin}{path}</loc></url>' for path in ('/', '/regulamin', '/prywatnosc'))
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + urls + '</urlset>', media_type='application/xml', headers={'Cache-Control': 'public, max-age=3600'})


@app.get('/llms.txt')
def llms(request: Request):
    origin = _origin(request)
    price = os.getenv('PLAN_PRICE', '').strip() or 'cena widoczna przy płatności'
    text = (f'# {BRAND}\n\n'
            f'> {BRAND} to płatny asystent randkowy AI dla dorosłych (18+). Pisze szkice odpowiedzi na Tinderze w stylu użytkownika '
            f'i podpowiada, kiedy zaprosić na randkę. Domyślnie użytkownik zatwierdza każdą wiadomość; w wybranych rozmowach może włączyć autopilota '
            f'i dostawać powiadomienia o umówionych randkach, Instagramie lub numerze. Cena: {price}, anulowanie w każdej chwili. '
            f'{BRAND} nie jest jeszcze powiązany z żadną aplikacją randkową.\n\n'
            f'## Strony\n\n'
            f'- [Strona główna]({origin}/): co robi {BRAND}, jak działa, cennik i najczęstsze pytania\n'
            f'- [Regulamin]({origin}/regulamin): zasady korzystania z usługi\n'
            f'- [Polityka prywatności]({origin}/prywatnosc): jak przetwarzamy dane\n')
    return PlainTextResponse(text, headers={'Cache-Control': 'public, max-age=3600'})


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
    stats = request.query_params.get('view') == 'stats'  # the weekly e-mail links straight to the statistics tab
    acc = current_account(request)
    if not acc:
        return RedirectResponse('/zaloguj' + ('?next=' + quote('/konto/panel?view=stats', safe='') if stats else ''), 303)
    if acc['status'] != 'active' or not acc.get('instance_url') or not acc.get('sso_secret') or not has_access(acc):
        return RedirectResponse('/konto', 303)
    return RedirectResponse(panel_url(acc) + '/auth/sso?t=' + sso_token(acc) + ('&next=stats' if stats else ''), 303)


# Public demo: the bot's real panel (static/dashboard.html at the repo root) on invented data.
# control/static/demo.js answers the panel's API calls inside the browser, so no bot and no account are involved.
BOT_STATIC = BASE.parent / 'static'
DEMO_FILES = {'dashboard.js': (BOT_STATIC, 'text/javascript'), 'icon.svg': (BOT_STATIC, 'image/svg+xml'),
              'fonts/fonts.css': (BOT_STATIC, 'text/css'), 'demo.js': (STATIC, 'text/javascript')}
DEMO_BAR = ('<div role="note" style="display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:6px 14px;'
            'padding:8px 16px;background:#2a0f1f;color:#fff;font:600 13px/1.3 Onest,system-ui,sans-serif;text-align:center">'
            '<span>Demo na fikcyjnych danych</span>'
            '<a href="/rejestracja" style="padding:5px 12px;border-radius:999px;color:#fff;text-decoration:none;'
            'background:linear-gradient(135deg,#fd267a,#ff6036)">Załóż konto</a></div>')


@app.get('/demo')
def demo():
    html = (BOT_STATIC / 'dashboard.html').read_text(encoding='utf-8').replace('/static/', '/demo/static/')
    html = html.replace('<title>Winq · panel</title>', f'<title>{BRAND} · demo panelu</title><meta name="robots" content="noindex">', 1)
    html = html.replace('<script src="/demo/static/dashboard.js"', '<script src="/demo/static/demo.js" defer></script>'
                        '<script src="/demo/static/dashboard.js"', 1)
    html = re.sub(r'<body([^>]*)>', lambda m: m.group(0) + DEMO_BAR, html, count=1)
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})


@app.get('/demo/static/{name:path}')
def demo_static(name: str):
    if re.fullmatch(r'fonts/[a-z-]+\.woff2', name) and (BOT_STATIC / name).is_file():
        return FileResponse(BOT_STATIC / name, media_type='font/woff2', headers={'Cache-Control': 'public, max-age=604800'})
    if name not in DEMO_FILES:
        raise HTTPException(404)
    folder, kind = DEMO_FILES[name]
    return FileResponse(folder / name, media_type=kind,
                        headers={'Cache-Control': 'no-cache'})


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
    source = body.get('source') if body.get('source') in SIGNUP_SOURCES else None
    q('INSERT INTO accounts(email,name,pw_hash,status,mode,consent_marketing,created,comped,source) VALUES(?,?,?,?,?,?,?,?,?)',
      (email, str(body.get('name', '')).strip()[:60], hash_password(password), 'pending', mode, int(body.get('marketing') is True), time.time(), int(comped), source))
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
            'trial_days': trial_days(), 'plans': catalog.public() if catalog.enabled() else [], 'plan': acc.get('plan') or '', 'plan_period': acc.get('plan_period') or '1',
            'panel_ready': acc['status'] == 'active' and bool(acc.get('instance_url')) and bool(acc.get('sso_secret')) and has_access(acc),
            'weekly_summary': acc.get('weekly_summary') != 0, 'setup': setup_progress(acc)}


@app.post('/api/account/weekly')
async def weekly_preference(request: Request):
    acc = current_account(request)
    if not acc:
        raise HTTPException(401, 'Nie jesteś zalogowany.')
    _same_origin(request)
    body = await _json(request)
    q('UPDATE accounts SET weekly_summary=? WHERE id=?', (int(body.get('enabled') is True), acc['id']))
    return {'ok': True, 'weekly_summary': body.get('enabled') is True}


def _unsub_account(token: str) -> dict | None:
    if not token or len(token) > 80:
        return None
    rows = q('SELECT id,email FROM accounts WHERE unsub_token=?', (token,), fetch=True)
    return rows[0] if rows else None


@app.get('/wypisz-sie')
def unsubscribe_page(t: str = ''):
    if not _unsub_account(t):
        return page('unsubscribe.html', {'{{UNSUB_BODY}}': '<h1>Ten link jest nieprawidłowy</h1><p class="sub">Podsumowania wyłączysz też na stronie konta.</p>'
                                                         '<a class="btn wide" href="/konto">Przejdź do konta</a>'})
    return page('unsubscribe.html', {'{{UNSUB_BODY}}': '<h1>Wypisać Cię z podsumowań?</h1><p class="sub">Przestaniemy wysyłać cotygodniowe podsumowanie. '
        f'Ważne wiadomości o koncie i płatnościach nadal będą przychodzić.</p><form method="post" action="/wypisz-sie?t={html_lib.escape(quote(t, safe=""))}">'
        '<button class="btn wide" type="submit">Tak, wypisz mnie</button></form>'})


@app.post('/wypisz-sie')
def unsubscribe(t: str = ''):
    """Also the target of the one-click List-Unsubscribe header: the token is the proof, no login needed."""
    acc = _unsub_account(t)
    if not acc:
        raise HTTPException(404, 'Nieprawidłowy link')
    q('UPDATE accounts SET weekly_summary=0 WHERE id=?', (acc['id'],))
    return page('unsubscribe.html', {'{{UNSUB_BODY}}': '<h1>Gotowe, wypisaliśmy Cię</h1><p class="sub">Nie wyślemy już cotygodniowego podsumowania. '
                                                      'Możesz je włączyć z powrotem na stronie konta.</p><a class="btn wide" href="/konto">Przejdź do konta</a>'})


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
        status = provision.deploy_status(service_id) if provision.can_query(service_id) else 'unknown'
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
async def delete_account(request: Request, tasks: BackgroundTasks):
    body = await _json(request)
    acc = current_account(request)
    if not acc:
        raise HTTPException(401, 'Nie jesteś zalogowany.')
    if not check_password(str(body.get('password', '')), acc['pw_hash']):
        raise HTTPException(401, 'Nieprawidłowe hasło.')
    # The customer's own bot holds their conversations and the encrypted Tinder token: it goes with the account. It is written
    # down first, so a provider hiccup never leaves a forgotten server behind; removal then retries until it works.
    sid = (acc.get('render_service_id') or '').strip()
    if sid and not is_owner(acc['email']) and sid != os.getenv('OWNER_SERVICE_ID', '').strip():
        q('INSERT INTO instance_removals(service_id,created) VALUES(?,?) ON CONFLICT(service_id) DO NOTHING', (sid, time.time()))
    q('DELETE FROM account_sessions WHERE account_id=?', (acc['id'],))
    q('DELETE FROM accounts WHERE id=?', (acc['id'],))
    tasks.add_task(remove_pending_instances)
    tasks.add_task(mailer.account_deleted, acc['email'])
    return _cookie(JSONResponse({'deleted': True}), None)


def remove_pending_instances() -> dict:
    """Delete the bots of deleted accounts. A failure keeps the entry (with the reason) for the next pass; success removes it."""
    done, failed = 0, 0
    for row in q('SELECT service_id FROM instance_removals ORDER BY created', fetch=True):
        sid = row['service_id']
        try:
            if not provision.can_query(sid):
                raise RuntimeError('hosting API is not configured')
            provision.delete_instance(sid)
        except Exception as exc:  # the reason only, never a token or a response body
            q('UPDATE instance_removals SET attempts=attempts+1, last_error=? WHERE service_id=?', (f'{type(exc).__name__}: {str(exc)[:160]}', sid))
            log.warning('removing instance %s failed: %s: %s', sid, type(exc).__name__, str(exc)[:160])
            failed += 1
            continue
        q('DELETE FROM instance_removals WHERE service_id=?', (sid,))
        log.info('removed instance %s of a deleted account', sid)
        done += 1
    return {'removed': done, 'failed': failed}


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
    chosen = None
    if catalog.enabled():
        chosen = catalog.get(body.get('plan'))
        if not chosen:
            raise HTTPException(422, 'Wybierz pakiet.')
        per = catalog.period(body.get('period'))
        if not per or (per['key'] != '1' and not catalog.periods_enabled()):
            raise HTTPException(422, 'Wybierz okres.')
        q('UPDATE accounts SET plan_choice=?, period_choice=? WHERE id=?', (chosen['slug'], per['key'], acc['id']))
    if link_mode():
        from urllib.parse import urlencode
        return {'url': (catalog.link_for(chosen['slug'], per['key']) if chosen else os.environ['STRIPE_PAYMENT_LINK']) + '?' + urlencode({'client_reference_id': str(acc['id']), 'prefilled_email': acc['email'], 'locale': 'pl'})}
    import stripe
    params = dict(mode='subscription', line_items=[{'price': os.environ['STRIPE_PRICE_ID'], 'quantity': 1}],
                  client_reference_id=str(acc['id']), success_url=_origin(request) + '/konto?platnosc=ok',
                  cancel_url=_origin(request) + '/konto', allow_promotion_codes=True, locale='pl',
                  metadata={'account_id': str(acc['id'])}, subscription_data={'metadata': {'account_id': str(acc['id'])}, **({'trial_period_days': trial_days()} if trial_days() else {})},
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
            q("UPDATE accounts SET stripe_customer=?, plan_status='active', withdrawn_at=NULL, paid_at=COALESCE(paid_at, ?), plan=COALESCE(plan_choice, plan), plan_period=COALESCE(period_choice, plan_period) WHERE id=?",
              (obj.get('customer'), time.time(), int(ref)))
            rows = q('SELECT email, plan, render_service_id FROM accounts WHERE id=?', (int(ref),), fetch=True)
            if rows:
                tasks.add_task(mailer.payment_ok, rows[0]['email'], _origin(request))
                tasks.add_task(run_provision, int(ref), _origin(request))
                if rows[0].get('render_service_id') and catalog.get(rows[0].get('plan')):
                    tasks.add_task(_apply_plan, rows[0]['render_service_id'], rows[0]['plan'])  # came back with another plan
    elif event['type'] in ('customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted'):
        status = 'canceled' if event['type'] == 'customer.subscription.deleted' else str(obj.get('status', 'none'))
        # A withdrawn contract stays withdrawn until the owner cancels it in Stripe; only a fresh checkout reopens it.
        # The customer switched plan in the Stripe portal (or someone changed it in Stripe): the plan follows the price.
        items = ((obj.get('items') or {}).get('data') or [{}])
        found = None if event['type'] == 'customer.subscription.deleted' else catalog.plan_for_price(((items[0] or {}).get('price') or {}).get('id'))
        if found:
            new_plan, new_period = found
            for acc_ in q('SELECT id, plan, plan_period, render_service_id FROM accounts WHERE stripe_customer=? AND withdrawn_at IS NULL', (obj.get('customer'),), fetch=True):
                if acc_.get('plan') != new_plan or (acc_.get('plan_period') or '1') != new_period:
                    q('UPDATE accounts SET plan=?, plan_choice=?, plan_period=?, period_choice=? WHERE id=?', (new_plan, new_plan, new_period, new_period, acc_['id']))
                if acc_.get('plan') != new_plan and acc_.get('render_service_id'):
                    tasks.add_task(_apply_plan, acc_['render_service_id'], new_plan)
        before = q('SELECT email, plan_status FROM accounts WHERE stripe_customer=? AND withdrawn_at IS NULL', (obj.get('customer'),), fetch=True)
        q('UPDATE accounts SET plan_status=? WHERE stripe_customer=? AND withdrawn_at IS NULL', (status[:30], obj.get('customer')))
        for row in before:  # one mail per change of state: Stripe repeats these events
            if row['plan_status'] == status[:30]:
                continue
            if status in ('past_due', 'unpaid'):
                tasks.add_task(mailer.payment_failed, row['email'], _origin(request))
            elif status == 'canceled':
                tasks.add_task(mailer.subscription_canceled, row['email'], _origin(request))
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
        inst = provision.create_instance(account_id, (catalog.get(acc.get('plan')) or {}).get('slug'))
    except Exception as exc:
        q("UPDATE accounts SET provision_state='failed', provision_error=? WHERE id=?", (type(exc).__name__ + ': ' + str(exc)[:240], account_id))
        return 'failed'
    if not q('SELECT 1 FROM accounts WHERE id=?', (account_id,), fetch=True):  # deleted while the server was being built
        q('INSERT INTO instance_removals(service_id,created) VALUES(?,?) ON CONFLICT(service_id) DO NOTHING', (inst['service_id'], time.time()))
        remove_pending_instances()
        return 'missing'
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


def _apply_plan(service_id: str, plan: str) -> None:
    try:
        provision.set_plan(service_id, plan)
    except Exception:
        pass


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
    if not rows:
        # Registration already tells whether an address is taken, so hiding it here protected nothing and only
        # left people waiting for an e-mail that never comes. Rate limits above still apply.
        raise HTTPException(404, 'Nie ma konta z tym adresem e-mail. Sprawdź, czy nie ma literówki, albo załóż konto.')
    if rows:
        raw = secrets.token_urlsafe(32)
        q('DELETE FROM password_resets WHERE account_id=? OR expires<?', (rows[0]['id'], time.time()))
        q('INSERT INTO password_resets VALUES(?,?,?)', (_sid(raw), rows[0]['id'], time.time() + 3600))
        tasks.add_task(mailer.password_reset, email, _origin(request) + '/nowe-haslo?t=' + raw)
    return {'ok': True}


@app.post('/api/password/reset')
async def password_reset(request: Request, tasks: BackgroundTasks):
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
    owner_row = q('SELECT email FROM accounts WHERE id=?', (aid,), fetch=True)
    if owner_row:
        tasks.add_task(mailer.password_changed, owner_row[0]['email'], _origin(request))
    return _cookie(JSONResponse({'ok': True}), new_session(aid))


def _admin(request: Request):
    expected = os.getenv('ADMIN_TOKEN', '')
    supplied = request.headers.get('authorization', '').removeprefix('Bearer ').strip()
    if len(expected) < 24 or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, 'Unauthorized')


@app.get('/admin/accounts')
def admin_accounts(request: Request):
    _admin(request)
    rows = q('SELECT email,name,status,plan_status,comped,instance_url,render_service_id,provision_state,provision_error,mode,source,consent_marketing,created,'
             'weekly_summary,weekly_sent_at,weekly_note '
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


@app.get('/admin/instances/removals')
def admin_removals(request: Request):
    """Bots of deleted accounts still waiting to be removed (with the last error). POST /admin/instances/removals retries now."""
    _admin(request)
    rows = q('SELECT service_id,created,attempts,last_error FROM instance_removals ORDER BY created', fetch=True)
    return {'count': len(rows), 'items': rows}


@app.post('/admin/instances/removals')
async def admin_removals_retry(request: Request):
    _admin(request)
    result = await asyncio.to_thread(remove_pending_instances)
    return {**result, 'left': len(q('SELECT 1 FROM instance_removals', fetch=True))}


@app.post('/admin/weekly/run')
async def admin_weekly_run(request: Request):
    """Run the weekly summary pass now. {"dry_run": true} composes and reports without sending or marking anything;
    {"force": true} ignores the weekly window and the one-per-week rule; {"email": "..."} limits it to one account."""
    _admin(request)
    body = await _json(request)
    kw = {'force': body.get('force') is True, 'dry_run': body.get('dry_run') is True, 'email': str(body['email']) if body.get('email') else None}
    results = await asyncio.to_thread(run_weekly, time.time(), **kw)
    return {'count': len(results), 'sent': sum(1 for r in results if r['result'] == 'sent'), 'items': results}


@app.get('/admin/fleet')
async def admin_fleet(request: Request):
    """Every customer's bot as the bot reports itself: reachable, Tinder connected, data fresh, agent running."""
    _admin(request)
    items = await asyncio.to_thread(weekly.check_fleet, q, base_for=panel_url, has_access=has_access)
    bad = [i for i in items if not i['reachable'] or i.get('status') == 'problem']
    return {'count': len(items), 'reachable': sum(1 for i in items if i['reachable']), 'problems': len(bad), 'items': items}


@app.post('/admin/mail/test')
async def admin_mail_test(request: Request, tasks: BackgroundTasks):
    """Send one sample of every customer mail to the given address, through the real sender (Resend), to check the look."""
    _admin(request)
    body = await _json(request)
    to = str(body.get('to', '')).strip()
    if '@' not in to or len(to) > 200:
        raise HTTPException(422, 'Podaj adres e-mail w polu "to".')
    o = _origin(request)
    sample = [lambda: mailer.welcome(to, o), lambda: mailer.payment_ok(to, o), lambda: mailer.panel_ready(to, o),
              lambda: mailer.password_reset(to, o + '/nowe-haslo?t=PRZYKLAD'), lambda: mailer.password_changed(to, o),
              lambda: mailer.payment_failed(to, o), lambda: mailer.subscription_canceled(to, o),
              lambda: mailer.withdrawal_confirmed(to, o), lambda: mailer.account_deleted(to)]

    def send_all():
        for send in sample:
            send()
            time.sleep(1.2)  # stay under the provider's rate limit
    tasks.add_task(send_all)
    return {'sending': len(sample), 'to': to, 'sender_problem': mailer.sender_problem()}


@app.post('/admin/fly/update-image')
async def admin_fly_update_image(request: Request, tasks: BackgroundTasks):
    """Roll every customer bot on Fly to a new image (default FLY_IMAGE), one at a time, in the background."""
    _admin(request)
    from control import fly
    body = await _json(request)
    image = str(body.get('image') or os.getenv('FLY_IMAGE', '')).strip()
    if not image.startswith('registry.fly.io/') or not fly.api_ready():
        raise HTTPException(422, 'Fly is not configured or the image is not in registry.fly.io')
    apps = [r['render_service_id'][4:] for r in q("SELECT render_service_id FROM accounts WHERE render_service_id LIKE 'fly:%'", fetch=True)]
    tasks.add_task(fly.update_all, apps, image)
    return {'updating': len(apps), 'image': image}


@app.get('/admin/waitlist')
def admin_waitlist(request: Request):
    _admin(request)
    rows = list_signups()
    return JSONResponse({'count': len(rows), 'items': rows})
