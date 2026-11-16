"""The plans customers can buy (Winq / Flirt / Casanova): names, prices, limits and what each one says on the pages.

A plan is "on sale" only when all three Stripe payment links are configured (STRIPE_LINK_WINQ, STRIPE_LINK_FLIRT,
STRIPE_LINK_CASANOVA). Until then the site sells its single plan as before. The limits here are for display; the bot
enforces them itself from its PLAN setting (agent/plans.py), so keep the two in step.
"""
from __future__ import annotations

import os

PLANS = [
    {'slug': 'winq', 'name': 'Winq', 'price': 19, 'conversations': 3, 'autopilot': False,
     'tagline': 'Na spokojny start', 'pitch': 'Winq podpowiada, Ty decydujesz, co wysłać.',
     'features': ['Szkice odpowiedzi w Twoim stylu', 'Do 3 aktywnych rozmów naraz', 'Ty klikasz „Wyślij”',
                  'Podstawowe statystyki', 'Własny serwer i szyfrowany token']},
    {'slug': 'flirt', 'name': 'Flirt', 'price': 69, 'conversations': 10, 'autopilot': True, 'popular': True,
     'tagline': 'Niech Winq pisze za Ciebie', 'pitch': 'Autopilot odpisuje, gdy ktoś Ci napisze, i proponuje spotkanie we właściwym momencie.',
     'features': ['Autopilot: odpisuje sam w Twoim stylu', 'Do 10 aktywnych rozmów naraz',
                  'Zaproszenie na randkę, gdy rozmowa jest gotowa', 'Powiadomienie, gdy randka jest umówiona',
                  'Podstawowe statystyki: rozmowy, odpowiedzi, wiadomości']},
    {'slug': 'casanova', 'name': 'Casanova', 'price': 169, 'conversations': 30, 'autopilot': True,
     'tagline': 'Dla tych, którzy mają dużo rozmów', 'pitch': 'Wszystko z Flirta, dla większej liczby rozmów naraz.',
     'features': ['Wszystko, co w Flircie', 'Do 30 aktywnych rozmów naraz',
                  'Zaawansowane statystyki: lejek od dopasowania do randki, aktywność dzień po dniu, zweryfikowane rezultaty',
                  'Priorytet we wsparciu']},
]


# Longer plans: pay for fewer months than you get. 6 months = 5 paid (1 free), 12 months = 9 paid (3 free).
PERIODS = [{'key': '1', 'months': 1, 'free': 0, 'label': 'Miesięcznie'},
           {'key': '6', 'months': 6, 'free': 1, 'label': '6 miesięcy'},
           {'key': '12', 'months': 12, 'free': 3, 'label': 'Rok'}]


def period(key: str | None) -> dict | None:
    return next((p for p in PERIODS if p['key'] == str(key or '1').strip()), None)


def total(plan: dict, per: dict) -> int:
    """What the customer pays up front for the whole period."""
    return plan['price'] * (per['months'] - per['free'])


def _suffix(per_key: str) -> str:
    return '' if per_key == '1' else '_' + per_key


def link_for(slug: str, per_key: str = '1') -> str:
    return os.getenv(f'STRIPE_LINK_{slug.upper()}{_suffix(per_key)}', '').strip()


def periods_enabled() -> bool:
    """The 6- and 12-month options are offered only when every plan has a payment link for each of them."""
    return enabled() and all(link_for(p['slug'], q['key']).startswith('https://') for p in PLANS for q in PERIODS if q['key'] != '1')


def price_id_for(slug: str, per_key: str = '1') -> str:
    return os.getenv(f'STRIPE_PRICE_{slug.upper()}{_suffix(per_key)}', '').strip()


def plan_for_price(price_id: str | None) -> tuple[str, str] | None:
    """(plan, period) a Stripe price belongs to: STRIPE_PRICE_<PLAN> is monthly, _6 and _12 the longer ones."""
    if not price_id:
        return None
    return next(((p['slug'], q['key']) for p in PLANS for q in PERIODS if price_id_for(p['slug'], q['key']) == price_id), None)


def enabled() -> bool:
    return all(link_for(p['slug']).startswith('https://') for p in PLANS)


def get(slug: str | None) -> dict | None:
    return next((p for p in PLANS if p['slug'] == (slug or '').strip().lower()), None)


def public() -> list[dict]:
    """What the account page needs (no links: the server chooses the link)."""
    keys = ('slug', 'name', 'price', 'conversations', 'autopilot', 'tagline', 'pitch', 'features', 'popular')
    out = []
    for p in PLANS:
        item = {k: p.get(k) for k in keys}
        item['periods'] = [{'key': q['key'], 'months': q['months'], 'free': q['free'], 'label': q['label'], 'total': total(p, q),
                            'per_month': round(total(p, q) / q['months'], 2), 'regular': p['price'] * q['months']}
                           for q in PERIODS if q['key'] == '1' or periods_enabled()]
        out.append(item)
    return out
