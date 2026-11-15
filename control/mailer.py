"""Transactional e-mail over SMTP (e.g. Gmail with an app password, or any provider).

Configured by SMTP_HOST, SMTP_PORT (587, STARTTLS), SMTP_USERNAME, SMTP_PASSWORD and MAIL_FROM.
Without SMTP_HOST nothing is sent and the call reports False, so the app keeps working.
Messages never contain conversation content or Tinder data.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

log = logging.getLogger('uvicorn.error')  # shows up in the service logs next to uvicorn's own lines
SENT: list[dict] = []  # tests read this when SMTP is not configured


def configured() -> bool:
    # A username without its password (not set yet) counts as not configured, so nothing tries to log in.
    return bool(os.getenv('SMTP_HOST')) and (not os.getenv('SMTP_USERNAME') or bool(os.getenv('SMTP_PASSWORD')))


def send(to: str, subject: str, text: str) -> bool:
    brand = os.getenv('BRAND_NAME', 'Winq')
    if not configured():
        SENT.append({'to': to, 'subject': subject, 'text': text})
        missing = [k for k in ('SMTP_HOST', 'SMTP_PASSWORD') if not os.getenv(k)]
        log.warning('mail not sent (%s): SMTP not configured, missing %s', subject, ', '.join(missing))
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr((brand, os.getenv('MAIL_FROM') or os.getenv('SMTP_USERNAME', '')))
    msg['To'] = to
    msg.set_content(text + f'\n\n{brand}\n' + os.getenv('PUBLIC_ORIGIN', '').rstrip('/'))
    with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.getenv('SMTP_PORT', '587')), timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        if os.getenv('SMTP_USERNAME'):
            s.login(os.environ['SMTP_USERNAME'], os.environ.get('SMTP_PASSWORD', ''))
        s.send_message(msg)
    log.info('mail sent (%s) via %s', subject, os.environ['SMTP_HOST'])
    return True


def safe_send(to: str, subject: str, text: str) -> None:
    """For background tasks: a mail failure must never break signup, payment or provisioning."""
    try:
        send(to, subject, text)
    except Exception as exc:  # the reason only: never the password or the message body
        log.error('mail failed (%s): %s: %s', subject, type(exc).__name__, str(exc)[:200])


def welcome(to: str, origin: str) -> None:
    safe_send(to, 'Witaj w Winq', 'Twoje konto jest gotowe.\n\nNastępny krok: wykup dostęp na stronie konta, '
              f'a przygotujemy Twój osobny serwer.\n{origin}/konto')


def payment_ok(to: str, origin: str) -> None:
    safe_send(to, 'Płatność przyjęta', 'Dziękujemy! Przygotowujemy Twój osobny serwer. Napiszemy, gdy panel będzie gotowy.\n'
              f'Subskrypcją zarządzasz na stronie konta: {origin}/konto')


def panel_ready(to: str, origin: str) -> None:
    safe_send(to, 'Twój panel jest gotowy', 'Twój panel czeka. Zaloguj się, kliknij „Otwórz mój panel" i połącz konto Tinder '
              f'(Ustawienia, Tinder). Zajmie to około 2 minut.\n{origin}/konto')


def withdrawal_confirmed(to: str, origin: str) -> None:
    safe_send(to, 'Potwierdzamy odstąpienie od umowy', 'Otrzymaliśmy Twoje oświadczenie o odstąpieniu od umowy. Subskrypcja '
              'zostanie anulowana, a zwrot (pomniejszony o dni korzystania z usługi) trafi na Twoją metodę płatności '
              f'w ciągu 14 dni. Konto i dane możesz usunąć na stronie konta: {origin}/konto')


def password_reset(to: str, link: str) -> None:
    safe_send(to, 'Ustaw nowe hasło', 'Ktoś (mamy nadzieję, że Ty) poprosił o zmianę hasła. Link działa przez godzinę:\n'
              f'{link}\n\nJeśli to nie Ty, zignoruj tę wiadomość. Twoje hasło się nie zmieni.')
