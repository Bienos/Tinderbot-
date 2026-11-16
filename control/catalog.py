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
                  'Własny serwer i szyfrowany token']},
    {'slug': 'flirt', 'name': 'Flirt', 'price': 69, 'conversations': 10, 'autopilot': True, 'popular': True,
     'tagline': 'Niech Winq pisze za Ciebie', 'pitch': 'Autopilot odpisuje, gdy ktoś Ci napisze, i proponuje spotkanie we właściwym momencie.',
     'features': ['Autopilot: odpisuje sam w Twoim stylu', 'Do 10 aktywnych rozmów naraz',
                  'Zaproszenie na randkę, gdy rozmowa jest gotowa', 'Powiadomienie, gdy randka jest umówiona',
                  'Statystyki od dopasowania do spotkania']},
    {'slug': 'casanova', 'name': 'Casanova', 'price': 169, 'conversations': 30, 'autopilot': True,
     'tagline': 'Dla tych, którzy mają dużo rozmów', 'pitch': 'Wszystko z Flirta, dla większej liczby rozmów naraz.',
     'features': ['Wszystko, co w Flircie', 'Do 30 aktywnych rozmów naraz', 'Priorytet we wsparciu']},
]


def link_for(slug: str) -> str:
    return os.getenv(f'STRIPE_LINK_{slug.upper()}', '').strip()


def enabled() -> bool:
    return all(link_for(p['slug']).startswith('https://') for p in PLANS)


def get(slug: str | None) -> dict | None:
    return next((p for p in PLANS if p['slug'] == (slug or '').strip().lower()), None)


def public() -> list[dict]:
    """What the account page needs (no links: the server chooses the link)."""
    keys = ('slug', 'name', 'price', 'conversations', 'autopilot', 'tagline', 'pitch', 'features', 'popular')
    return [{k: p.get(k) for k in keys} for p in PLANS]
