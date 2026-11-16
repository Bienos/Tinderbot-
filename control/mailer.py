"""Transactional e-mail over SMTP (e.g. Gmail with an app password, or any provider).

Configured by SMTP_HOST, SMTP_PORT (587, STARTTLS), SMTP_USERNAME, SMTP_PASSWORD and MAIL_FROM
(MAIL_REPLY_TO is optional, it defaults to MAIL_FROM so replies reach a mailbox someone reads).
Without SMTP_HOST nothing is sent and the call reports False, so the app keeps working.
Messages never contain conversation content or Tinder data.

Every message is one small spec (subject, heading, paragraphs, optional button) rendered twice, as the plain-text
and the HTML part, so the two can never drift apart. All wording lives in the functions at the bottom.
"""
from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

log = logging.getLogger('uvicorn.error')  # shows up in the service logs next to uvicorn's own lines
SENT: list[dict] = []  # tests read this when SMTP is not configured

EMBER, INK, TEXT, MUTED, LINE, BG = '#fd267a', '#2a0f22', '#57404f', '#8a7482', '#f0e3e9', '#fff6f8'


def configured() -> bool:
    # A username without its password (not set yet) counts as not configured, so nothing tries to log in.
    return bool(os.getenv('SMTP_HOST')) and (not os.getenv('SMTP_USERNAME') or bool(os.getenv('SMTP_PASSWORD')))


def _brand() -> str:
    return os.getenv('BRAND_NAME', 'Winq')


def _origin() -> str:
    return os.getenv('PUBLIC_ORIGIN', '').rstrip('/')


def _contact() -> str:
    return os.getenv('MAIL_REPLY_TO') or os.getenv('MAIL_FROM') or os.getenv('LEGAL_EMAIL', '') or os.getenv('SMTP_USERNAME', '')


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
    paras = spec['paragraphs']
    btn = spec.get('button')
    note = spec.get('note')
    why = spec.get('why', 'To wiadomość serwisowa, wysłana, bo masz konto w ' + brand + '.')

    # plain text
    lines = [spec['heading'], '']
    for p in paras:
        lines += [p, '']
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
    p_html = ''.join(f'<p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:{TEXT}">{e(p)}</p>' for p in paras)
    btn_html = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 20px"><tr><td style="border-radius:999px;background:{EMBER}">'
                f'<a href="{e(btn[1], quote=True)}" style="display:inline-block;padding:14px 28px;font-size:16px;font-weight:700;color:#ffffff;'
                f'text-decoration:none;border-radius:999px;background:linear-gradient(120deg,#fd267a,#ff6036)">{e(btn[0])}</a></td></tr></table>') if btn else ''
    link_line = f'<p style="margin:0 0 16px;font-size:13px;line-height:1.5;color:{MUTED}">Gdyby przycisk nie działał, wklej ten adres w przeglądarce:<br><span style="word-break:break-all">{e(btn[1])}</span></p>' if btn else ''
    note_html = f'<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:{MUTED}">{e(note)}</p>' if note else ''
    logo = f'{_origin()}/apple-touch-icon.png' if _origin() else ''
    logo_img = (f'<img src="{e(logo, quote=True)}" width="36" height="36" alt="" style="vertical-align:middle;border-radius:9px;border:0;margin-right:10px">' if logo else '')
    foot_links = ' · '.join(f'<a href="{e(u, quote=True)}" style="color:{MUTED};text-decoration:underline">{e(t)}</a>' for t, u in _links())
    contact_html = (f'Pytania? Odpisz na tę wiadomość albo napisz na <a href="mailto:{e(contact, quote=True)}" style="color:{EMBER};text-decoration:none">{e(contact)}</a>.<br>' if contact else '')
    page = f'''<!doctype html><html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{e(spec['subject'])}</title></head>
<body style="margin:0;padding:0;background:{BG}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG}">{e(spec.get('preheader', ''))}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}"><tr><td align="center" style="padding:28px 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px">
<tr><td style="padding:0 6px 18px;font-family:Arial,Helvetica,sans-serif">{logo_img}<span style="vertical-align:middle;font-size:24px;font-weight:700;color:{INK};letter-spacing:-.5px">{e(brand.lower())}</span></td></tr>
<tr><td style="background:#ffffff;border:1px solid {LINE};border-radius:18px;padding:32px 30px;font-family:Arial,Helvetica,sans-serif">
<h1 style="margin:0 0 18px;font-size:24px;line-height:1.25;color:{INK};font-weight:700">{e(spec['heading'])}</h1>
{p_html}{btn_html}{link_line}{note_html}
</td></tr>
<tr><td style="padding:20px 10px 0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.6;color:{MUTED};text-align:center">
{contact_html}{e(why)}<br>{e(seller)}{'<br>' if seller else ''}{foot_links}
</td></tr></table></td></tr></table></body></html>'''
    return text, page


def send_spec(to: str, spec: dict) -> bool:
    text, page = render(spec)
    if not configured():
        SENT.append({'to': to, 'subject': spec['subject'], 'text': text, 'html': page})
        missing = [k for k in ('SMTP_HOST', 'SMTP_PASSWORD') if not os.getenv(k)]
        log.warning('mail not sent (%s): SMTP not configured, missing %s', spec['subject'], ', '.join(missing))
        return False
    sender = os.getenv('MAIL_FROM') or os.getenv('SMTP_USERNAME', '')
    msg = EmailMessage()
    msg['Subject'] = spec['subject']
    msg['From'] = formataddr((_brand(), sender))
    msg['To'] = to
    reply_to = os.getenv('MAIL_REPLY_TO') or sender
    if reply_to:
        msg['Reply-To'] = reply_to
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
    _safe(to, {'subject': 'Witaj w Winq', 'preheader': 'Twoje konto jest gotowe. Został jeden krok.',
               'heading': 'Witaj w Winq!',
               'paragraphs': ['Twoje konto jest gotowe. Winq to Twój asystent do rozmów na Tinderze: pisze szkice odpowiedzi w Twoim stylu, '
                              'a gdy zechcesz, odpisuje sam.',
                              'Następny krok: wykup dostęp na stronie konta. Wtedy przygotujemy dla Ciebie osobny serwer, '
                              'zwykle w kilka minut.'],
               'button': ('Przejdź do konta', f'{origin}/konto')})


def payment_ok(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Płatność przyjęta', 'preheader': 'Dziękujemy! Przygotowujemy Twój serwer.',
               'heading': 'Dziękujemy za płatność',
               'paragraphs': ['Przygotowujemy Twój osobny serwer. To zwykle kilka minut, a gdy panel będzie gotowy, napiszemy do Ciebie.',
                              'Na stronie konta zobaczysz, jak idzie przygotowanie, i zarządzisz subskrypcją.'],
               'button': ('Otwórz konto', f'{origin}/konto')})


def panel_ready(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Twój panel jest gotowy', 'preheader': 'Połącz konto Tinder, to około 2 minuty.',
               'heading': 'Twój panel jest gotowy',
               'paragraphs': ['Zaloguj się, kliknij „Otwórz mój panel” i połącz konto Tinder (Ustawienia, Tinder). Zajmie to około 2 minut.',
                              'Potem wybierz styl, dopisz w bio zdanie, że używasz AI, i włącz autopilota. Panel poprowadzi Cię krok po kroku.'],
               'button': ('Otwórz konto', f'{origin}/konto')})


def password_reset(to: str, link: str) -> None:
    _safe(to, {'subject': 'Ustaw nowe hasło', 'preheader': 'Link działa przez godzinę.',
               'heading': 'Ustaw nowe hasło',
               'paragraphs': ['Ktoś (mamy nadzieję, że Ty) poprosił o zmianę hasła do konta w Winq. Link działa przez godzinę.'],
               'button': ('Ustaw nowe hasło', link),
               'note': 'Jeśli to nie Ty, zignoruj tę wiadomość. Twoje hasło się nie zmieni.'})


def password_changed(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Hasło zostało zmienione', 'preheader': 'Jeśli to nie Ty, zareaguj od razu.',
               'heading': 'Zmieniliśmy Twoje hasło',
               'paragraphs': ['Hasło do Twojego konta w Winq zostało właśnie zmienione, a wszystkie sesje wylogowane.',
                              'Jeśli to Ty, nic nie musisz robić. Jeśli nie, ustaw nowe hasło od razu i odpisz na tę wiadomość.'],
               'button': ('Ustaw nowe hasło', f'{origin}/nie-pamietam-hasla')})


def payment_failed(to: str, origin: str) -> None:
    _safe(to, {'subject': 'Nie udało się pobrać płatności', 'preheader': 'Zaktualizuj kartę, żeby nie stracić dostępu.',
               'heading': 'Nie udało się pobrać płatności',
               'paragraphs': ['Nie mogliśmy pobrać opłaty za subskrypcję. Najczęściej wystarczy zaktualizować kartę.',
                              'Twoje ustawienia i rozmowy są bezpieczne, ale bez płatności dostęp do panelu zostanie wstrzymany.'],
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
                              'Zwrot, pomniejszony o dni korzystania z usługi, trafi na Twoją metodę płatności w ciągu 14 dni.',
                              'Konto i dane możesz usunąć na stronie konta.'],
               'button': ('Przejdź do konta', f'{origin}/konto')})


def account_deleted(to: str) -> None:
    _safe(to, {'subject': 'Twoje konto zostało usunięte', 'preheader': 'Potwierdzenie usunięcia konta i danych.',
               'heading': 'Konto usunięte',
               'paragraphs': ['Usunęliśmy Twoje konto w Winq. Osobnego serwera z Twoim panelem i rozmowami nie kasujemy automatycznie: '
                              'jeśli z niego korzystałeś, odpisz na tę wiadomość, a usuniemy go razem z danymi.',
                              'Jeśli masz aktywną subskrypcję, anuluj ją, żeby nie pobierano opłat. Dziękujemy, że byłeś z nami.'],
               'why': 'To jednorazowe potwierdzenie. Nie wyślemy Ci już więcej wiadomości.'})
