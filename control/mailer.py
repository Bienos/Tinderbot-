"""Transactional e-mail over SMTP (e.g. Gmail with an app password, or any provider).

Configured by SMTP_HOST, SMTP_PORT (587, STARTTLS), SMTP_USERNAME, SMTP_PASSWORD and MAIL_FROM.
Without SMTP_HOST nothing is sent and the call reports False, so the app keeps working.
Messages never contain conversation content or Tinder data.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

SENT: list[dict] = []  # tests read this when SMTP is not configured


def configured() -> bool:
    return bool(os.getenv('SMTP_HOST'))


def send(to: str, subject: str, text: str) -> bool:
    brand = os.getenv('BRAND_NAME', 'Iskra')
    if not configured():
        SENT.append({'to': to, 'subject': subject, 'text': text})
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
    return True


def safe_send(to: str, subject: str, text: str) -> None:
    """For background tasks: a mail failure must never break signup, payment or provisioning."""
    try:
        send(to, subject, text)
    except Exception:
        pass


def welcome(to: str, origin: str) -> None:
    safe_send(to, 'Witaj w Iskrze', 'Twoje konto jest gotowe.\n\nNastępny krok: wykup dostęp na stronie konta, '
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
