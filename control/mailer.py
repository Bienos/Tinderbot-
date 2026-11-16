"""Transactional e-mail over SMTP.

Configured by SMTP_HOST, SMTP_PORT (587, STARTTLS), SMTP_USERNAME, SMTP_PASSWORD and MAIL_FROM
(MAIL_REPLY_TO is optional, it defaults to MAIL_FROM so replies reach a mailbox someone reads).
Without SMTP_HOST nothing is sent and the call reports False, so the app keeps working.
Messages never contain conversation content or Tinder data.

Mail only ever leaves from the brand's own domain. MAIL_FROM must be an address on the site's domain (the host of
PUBLIC_ORIGIN, or MAIL_DOMAIN), and a Gmail relay is refused because Gmail rewrites the From address to the account's
own. If either rule fails nothing is sent and the log says why: a mail from somebody's private address is worse than none.

Every message is one small spec (subject, heading, paragraphs, optional steps / callout / button) rendered twice,
as the plain-text and the HTML part, so the two can never drift apart. All wording lives at the bottom.
"""
from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlsplit

log = logging.getLogger('uvicorn.error')  # shows up in the service logs next to uvicorn's own lines
SENT: list[dict] = []  # tests read this when SMTP is not configured

EMBER, FLAME, INK, TEXT, MUTED, LINE, BG, SOFT = '#fd267a', '#ff6036', '#2a0f22', '#4a3643', '#8a7482', '#f0e3e9', '#fff6f8', '#fff1f5'
FONT = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
CALLOUTS = {'info': (SOFT, EMBER), 'warn': ('#fff8e6', '#f2a516'), 'ok': ('#effaf3', '#1f9d55')}


def configured() -> bool:
    # A username without its password (not set yet) counts as not configured, so nothing tries to log in.
    return bool(os.getenv('SMTP_HOST')) and (not os.getenv('SMTP_USERNAME') or bool(os.getenv('SMTP_PASSWORD')))


def _trial() -> int:
    try:
        return max(0, min(30, int(os.getenv('TRIAL_DAYS', '0') or 0)))
    except ValueError:
        return 0


def _days(n: int) -> str:
    return f'{n} dzień' if n == 1 else f'{n} dni'


def _brand() -> str:
    return os.getenv('BRAND_NAME', 'Winq')


def _origin() -> str:
    return os.getenv('PUBLIC_ORIGIN', '').rstrip('/')


def _domain() -> str:
    host = os.getenv('MAIL_DOMAIN', '').strip().lower() or (urlsplit(_origin()).hostname or '')
    return host.removeprefix('www.')


def _on_domain(address: str) -> bool:
    domain = _domain()
    host = address.rpartition('@')[2].strip().lower()
    return bool(address) and '@' in address and (not domain or host == domain or host.endswith('.' + domain))


def _contact() -> str:
    """The address shown in the footer and used for Reply-To: the first configured one on our own domain."""
    for key in ('MAIL_REPLY_TO', 'MAIL_FROM', 'LEGAL_EMAIL'):
        value = os.getenv(key, '').strip()
        if _on_domain(value):
            return value
    return ''


def sender_problem() -> str | None:
    """Why mail must not be sent right now, or None when the sender is fine."""
    sender = os.getenv('MAIL_FROM', '').strip()
    if not sender:
        return 'MAIL_FROM is not set'
    if not _on_domain(sender):
        return f'MAIL_FROM {sender} is not an address on {_domain()}'
    if os.getenv('SMTP_HOST', '').strip().lower().endswith(('gmail.com', 'googlemail.com')):
        return 'Gmail would replace the From address with its own account address'
    return None


def _seller() -> str:
    """Seller identity for the footer, only the fields that are really filled in (no template placeholders)."""
    parts = [os.getenv(k, '').strip() for k in ('LEGAL_NAME', 'LEGAL_ADDRESS', 'LEGAL_ID')]
    return ', '.join(p for p in parts if p and not p.startswith('['))


def _links() -> list[tuple[str, str]]:
    o = _origin()
    return [('Twoje konto', o + '/konto'), ('Regulamin', o + '/regulamin'), ('Polityka prywatności', o + '/prywatnosc')] if o else []


def render(spec: dict) -> tuple[str, str]:
    """(plain text, html) for one message spec."""
    brand, contact, seller = _brand(), _contact(), _seller()
    paras, steps = spec.get('paragraphs', []), spec.get('steps', [])
    btn, callout, note = spec.get('button'), spec.get('callout'), spec.get('note')
    why = spec.get('why', 'To wiadomość serwisowa, wysłana, bo masz konto w ' + brand + '.')

    # plain text
    lines = [spec['heading'], '']
    for p in paras:
        lines += [p, '']
    for n, (title, desc) in enumerate(steps, 1):
        lines.append(f'{n}. {title}' + (f' {desc}' if desc else ''))
    if steps:
        lines.append('')
    if callout:
        lines += [callout[1], '']
    if btn:
        lines += [f'{btn[0]}: {btn[1]}', '']
    if note:
        lines += [note, '']
    lines += ['—', brand]
    if contact:
        lines.append(f'Pytania? Odpisz na tę wiadomość albo napisz na {contact}.')
    lines.append(why)
    if seller:
        lines.append(seller)
    lines += [f'{t}: {u}' for t, u in _links()]
    text = '\n'.join(lines)

    # html: tables and inline styles only, because mail clients ignore almost everything else
    e = html.escape
    p_html = ''.join(f'<p style="margin:0 0 18px;font-size:16px;line-height:1.65;color:{TEXT}">{e(p)}</p>' for p in paras)
    steps_html = ''
    if steps:
        rows = ''.join(
            f'<tr><td width="40" valign="top" style="padding:12px 0 12px 16px"><table role="presentation" cellpadding="0" cellspacing="0"><tr>'
            f'<td width="28" height="28" align="center" valign="middle" bgcolor="{EMBER}" style="width:28px;height:28px;border-radius:14px;background:{EMBER};'
            f'color:#ffffff;font-size:14px;font-weight:700;line-height:28px;font-family:{FONT}">{n}</td></tr></table></td>'
            f'<td valign="top" style="padding:12px 16px 12px 8px;font-family:{FONT}"><div style="font-size:15px;font-weight:700;color:{INK};line-height:1.4">{e(title)}</div>'
            + (f'<div style="font-size:14px;color:{MUTED};line-height:1.5;margin-top:2px">{e(desc)}</div>' if desc else '') + '</td></tr>'
            for n, (title, desc) in enumerate(steps, 1))
        steps_html = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 22px;background:{SOFT};border-radius:14px">{rows}</table>')
    callout_html = ''
    if callout:
        bg, bar = CALLOUTS.get(callout[0], CALLOUTS['info'])
        callout_html = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:4px 0 22px"><tr>'
                        f'<td width="4" bgcolor="{bar}" style="width:4px;background:{bar};border-radius:4px"></td>'
                        f'<td style="padding:14px 16px;background:{bg};border-radius:0 12px 12px 0;font-family:{FONT};font-size:15px;line-height:1.55;color:{INK}">{e(callout[1])}</td></tr></table>')
    btn_html = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0 22px"><tr><td bgcolor="{EMBER}" style="border-radius:999px;background:{EMBER};'
                f'background-image:linear-gradient(120deg,{EMBER},{FLAME})"><a href="{e(btn[1], quote=True)}" style="display:inline-block;padding:16px 36px;font-family:{FONT};'
                f'font-size:16px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:999px">{e(btn[0])}</a></td></tr></table>') if btn else ''
    link_line = (f'<p style="margin:0 0 6px;font-size:12px;line-height:1.5;color:{MUTED}">Gdyby przycisk nie działał, wklej ten adres w przeglądarce:<br>'
                 f'<span style="word-break:break-all">{e(btn[1])}</span></p>') if btn else ''
    note_html = f'<p style="margin:18px 0 0;font-size:14px;line-height:1.6;color:{MUTED}">{e(note)}</p>' if note else ''
    origin = _origin()
    logo_img = (f'<img src="{e(origin + "/assets/email-logo.png", quote=True)}" width="140" height="34" alt="{e(brand.lower())}" '
                f'style="display:block;margin:0 auto;border:0;font-family:{FONT};font-size:26px;font-weight:700;color:{INK}">') if origin else \
        f'<span style="font-family:{FONT};font-size:26px;font-weight:700;color:{INK}">{e(brand.lower())}</span>'
    foot_links = ' &nbsp;·&nbsp; '.join(f'<a href="{e(u, quote=True)}" style="color:{MUTED};text-decoration:underline">{e(t)}</a>' for t, u in _links())
    contact_html = (f'Pytania? Odpisz na tę wiadomość albo napisz na <a href="mailto:{e(contact, quote=True)}" style="color:{EMBER};text-decoration:none;font-weight:600">{e(contact)}</a>.<br>' if contact else '')
    seller_html = f'{e(seller)}<br>' if seller else ''
    page = f'''<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>{e(spec['subject'])}</title></head>
<body style="margin:0;padding:0;background:{BG}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG}">{e(spec.get('preheader', ''))}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{BG}" style="background:{BG}"><tr><td align="center" style="padding:32px 14px 40px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">
<tr><td align="center" style="padding:0 0 22px">{logo_img}</td></tr>
<tr><td style="background:#ffffff;border:1px solid {LINE};border-radius:22px;overflow:hidden">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td height="8" bgcolor="{EMBER}" style="height:8px;line-height:8px;font-size:0;background:{EMBER};background-image:linear-gradient(120deg,{EMBER},{FLAME})">&nbsp;</td></tr>
<tr><td style="padding:36px 34px 30px;font-family:{FONT}">
<h1 style="margin:0 0 20px;font-size:27px;line-height:1.2;color:{INK};font-weight:800;letter-spacing:-.5px">{e(spec['heading'])}</h1>
{p_html}{steps_html}{callout_html}{btn_html}{link_line}{note_html}
</td></tr></table></td></tr>
<tr><td align="center" style="padding:24px 12px 0;font-family:{FONT};font-size:12px;line-height:1.7;color:{MUTED}">
{contact_html}{e(why)}<br>{seller_html}{foot_links}
</td></tr></table></td></tr></table></body></html>'''
    return text, page


def send_spec(to: str, spec: dict) -> bool:
    text, page = render(spec)
    if not configured():
        SENT.append({'to': to, 'subject': spec['subject'], 'text': text, 'html': page})
        missing = [k for k in ('SMTP_HOST', 'SMTP_PASSWORD') if not os.getenv(k)]
        log.warning('mail not sent (%s): SMTP not configured, missing %s', spec['subject'], ', '.join(missing))
        return False
    problem = sender_problem()
    if problem:
        log.error('mail NOT sent (%s): %s', spec['subject'], problem)
        return False
    sender = os.environ['MAIL_FROM'].strip()
    msg = EmailMessage()
    msg['Subject'] = spec['subject']
    msg['From'] = formataddr((_brand(), sender))
    msg['To'] = to
    msg['Reply-To'] = _contact() or sender
    msg.set_content(text)
    msg.add_alternative(page, subtype='html')
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')), timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        if os.getenv('SMTP_USERNAME'):
            s.login(os.environ['SMTP_USERNAME'], os.environ.get('SMTP_PASSWORD', ''))
        s.send_message(msg)
    log.info('mail sent (%s) via %s', spec['subject'], os.environ['SMTP_HOST'])
    return True


def send(to: str, subject: str, text: str) -> bool:
    """Plain wording in, the standard layout around it (used for internal notes to the owner)."""
    return send_spec(to, {'subject': subject, 'heading': subject, 'paragraphs': [p for p in text.split('\n') if p.strip()],
                          'why': 'Wiadomość wewnętrzna systemu ' + _brand() + '.'})


def _safe(to: str, spec: dict) -> None:
    """For background tasks: a mail failure must never break signup, payment or provisioning."""
    try:
        send_spec(to, spec)
    except Exception as exc:  # the reason only: never the password or the message body
        log.error('mail failed (%s): %s: %s', spec['subject'], type(exc).__name__, str(exc)[:200])


def safe_send(to: str, subject: str, text: str) -> None:
    try:
        send(to, subject, text)
    except Exception as exc:
        log.error('mail failed (%s): %s: %s', subject, type(exc).__name__, str(exc)[:200])


# ---- the messages: nine for customers, in the order a customer meets them (plus send() for notes to the owner)
def welcome(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Witaj w Winq', 'preheader': 'Twoje konto jest gotowe. Zostały trzy proste kroki.',
               'heading': 'Witaj w Winq! 👋',
               'paragraphs': ['Twoje konto jest gotowe. Winq to Twój asystent do rozmów na Tinderze: pisze szkice odpowiedzi w Twoim stylu, '
                              'a gdy zechcesz, odpisuje sam.', 'Tak zaczniesz:'],
               'steps': [(f'Zacznij {_days(_trial())} za darmo' if _trial() else 'Wykup dostęp', 'Na stronie konta. Anulujesz w każdej chwili.'),
                         ('Przygotujemy Twój osobny serwer', 'Zwykle w kilka minut. Napiszemy, gdy będzie gotowy.'),
                         ('Połącz Tinder i włącz autopilota', 'Panel poprowadzi Cię krok po kroku.')],
               'button': ('Przejdź do konta', f'{origin}/konto')})


def payment_ok(to: str, origin: str) -> None:
    n = _trial()
    if n:
        _safe(to, {'subject': 'Okres próbny rozpoczęty', 'preheader': f'Masz {_days(n)} za darmo. Dziś nic nie pobraliśmy.',
                   'heading': f'Masz {_days(n)} za darmo 🎉',
                   'paragraphs': ['Zapisaliśmy Twoją kartę, ale dziś nic z niej nie pobraliśmy. Przygotowujemy Twój osobny serwer. To zwykle kilka minut, a gdy panel będzie gotowy, napiszemy do Ciebie.'],
                   'callout': ('ok', f'Pierwsza opłata nastąpi po {_days(n)}. Jeśli zrezygnujesz wcześniej na stronie konta („Zarządzaj subskrypcją”), nic nie zapłacisz.'),
                   'button': ('Otwórz konto', f'{origin}/konto')})
        return
    _safe(to, {'subject': 'Płatność przyjęta', 'preheader': 'Dziękujemy! Przygotowujemy Twój serwer.',
               'heading': 'Dziękujemy za płatność 🎉',
               'paragraphs': ['Przygotowujemy Twój osobny serwer. To zwykle kilka minut, a gdy panel będzie gotowy, napiszemy do Ciebie.',
                              'Na stronie konta zobaczysz, jak idzie przygotowanie, i zarządzisz subskrypcją.'],
               'callout': ('ok', 'Nie musisz nic robić. Ta wiadomość to potwierdzenie, że wszystko jest w drodze.'),
               'button': ('Otwórz konto', f'{origin}/konto')})


def panel_ready(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Twój panel jest gotowy', 'preheader': 'Połącz konto Tinder i włącz autopilota. To około 3 minuty.',
               'heading': 'Twój panel jest gotowy 🚀',
               'paragraphs': ['Zaloguj się i kliknij „Otwórz mój panel”. Zostały cztery krótkie kroki, razem około 3 minut:'],
               'steps': [('Połącz konto Tinder', 'Ustawienia, Tinder. Wklejasz token, instrukcja jest przy polu.'),
                         ('Wybierz styl', 'Jedno kliknięcie. Zmienisz go, kiedy chcesz.'),
                         ('Dopisz „AI” w bio na Tinderze', 'Osoby, z którymi piszesz, mają wiedzieć, że pomaga Ci asystent.'),
                         ('Włącz autopilota', 'Od tej chwili Winq odpisuje sam, a pierwszą wiadomość do nowej pary piszesz Ty.')],
               'button': ('Otwórz konto', f'{origin}/konto')})


def password_reset(to: str, link: str) -> None:
    _safe(to, {'subject': 'Ustaw nowe hasło', 'preheader': 'Link działa przez godzinę.',
               'heading': 'Ustaw nowe hasło',
               'paragraphs': ['Ktoś (mamy nadzieję, że Ty) poprosił o zmianę hasła do konta w Winq. Kliknij przycisk, żeby ustawić nowe.'],
               'button': ('Ustaw nowe hasło', link),
               'callout': ('info', 'Link działa przez godzinę i tylko raz. Jeśli to nie Ty, zignoruj tę wiadomość, Twoje hasło się nie zmieni.')})


def password_changed(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Hasło zostało zmienione', 'preheader': 'Jeśli to nie Ty, zareaguj od razu.',
               'heading': 'Zmieniliśmy Twoje hasło',
               'paragraphs': ['Hasło do Twojego konta w Winq zostało właśnie zmienione, a wszystkie sesje wylogowane.'],
               'callout': ('warn', 'To nie Ty? Ustaw nowe hasło od razu i odpisz na tę wiadomość, a pomożemy zabezpieczyć konto.'),
               'button': ('Ustaw nowe hasło', f'{origin}/nie-pamietam-hasla')})


def payment_failed(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Nie udało się pobrać płatności', 'preheader': 'Zaktualizuj kartę, żeby nie stracić dostępu.',
               'heading': 'Nie udało się pobrać płatności',
               'paragraphs': ['Nie mogliśmy pobrać opłaty za subskrypcję. Najczęściej wystarczy zaktualizować kartę.'],
               'callout': ('warn', 'Twoje ustawienia i rozmowy są bezpieczne, ale bez płatności dostęp do panelu zostanie wstrzymany.'),
               'button': ('Zaktualizuj płatność', f'{origin}/konto')})


def subscription_canceled(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Subskrypcja została anulowana', 'preheader': 'Możesz wrócić, kiedy zechcesz.',
               'heading': 'Subskrypcja anulowana',
               'paragraphs': ['Twoja subskrypcja Winq została anulowana, a panel wstrzymany.',
                              'Konto i ustawienia zostają, więc jeśli zechcesz wrócić, wystarczy wznowić subskrypcję na stronie konta. '
                              'Dane możesz też usunąć w każdej chwili.'],
               'button': ('Przejdź do konta', f'{origin}/konto')})


def withdrawal_confirmed(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Potwierdzamy odstąpienie od umowy', 'preheader': 'Zwrot trafi do Ciebie w ciągu 14 dni.',
               'heading': 'Potwierdzamy odstąpienie od umowy',
               'paragraphs': ['Otrzymaliśmy Twoje oświadczenie o odstąpieniu od umowy. Subskrypcja zostanie anulowana.',
                              'Konto i dane możesz usunąć na stronie konta.'],
               'callout': ('ok', 'Zwrot, pomniejszony o dni korzystania z usługi, trafi na Twoją metodę płatności w ciągu 14 dni.'),
               'button': ('Przejdź do konta', f'{origin}/konto')})


def account_deleted(to: str) -> None:
    _safe(to, {'subject': 'Twoje konto zostało usunięte', 'preheader': 'Potwierdzenie usunięcia konta.',
               'heading': 'Konto usunięte',
               'paragraphs': ['Usunęliśmy Twoje konto w Winq. Dziękujemy, że byłeś z nami.'],
               'callout': ('info', 'Osobnego serwera z Twoim panelem i rozmowami nie kasujemy automatycznie. Jeśli z niego korzystałeś, odpisz na tę wiadomość, '
                                   'a usuniemy go razem z danymi. Jeśli masz aktywną subskrypcję, anuluj ją, żeby nie pobierano opłat.'),
               'why': 'To jednorazowe potwierdzenie. Nie wyślemy Ci już więcej wiadomości.'})
