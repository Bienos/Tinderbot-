"""The "stay with us" step of cancelling: a short survey (how satisfied, why leaving), then one offer.

The offer: BONUS more active conversations on the customer's current plan (for as long as they stay on that plan) and
DISCOUNT_PCT % off their next payment. Once per account. Both halves are only promised when we can deliver them:
- the extra conversations are a setting on the customer's own bot (PLAN_CONVERSATIONS), which we can always change;
- the discount needs the Stripe API (STRIPE_SECRET_KEY, a restricted key with Subscriptions and Coupons write access) and
  a monthly subscription. Without them the offer simply leaves the discount out, never promises it.
"""
from __future__ import annotations

import os

BONUS = 5
DISCOUNT_PCT = 30
COUPON_ID = 'winq-stay-30'

REASONS = [
    ('price', 'Za drogo'),
    ('few_conversations', 'Za mało aktywnych rozmów w pakiecie'),
    ('style', 'Odpowiedzi nie brzmiały jak ja'),
    ('results', 'Za mało randek i efektów'),
    ('technical', 'Problemy techniczne (połączenie z Tinderem, błędy)'),
    ('not_using', 'Nie korzystam już z Tindera'),
    ('met_someone', 'Poznałem lub poznałam kogoś'),
    ('safety', 'Obawiam się o bezpieczeństwo konta na Tinderze'),
    ('other', 'Inny powód'),
]
REASON_KEYS = {k for k, _ in REASONS}


def conversations_value(acc: dict, plan: dict | None) -> str:
    """What PLAN_CONVERSATIONS on the customer's bot should be: the plan's limit plus the bonus while they stay on the plan they
    accepted the offer on, otherwise an empty string (= the plan's own limit)."""
    if plan and acc.get('retention_used_at') and acc.get('retention_plan') and acc.get('retention_plan') == acc.get('plan'):
        return str(int(plan['conversations']) + BONUS)
    return ''


def discount_possible(acc: dict) -> bool:
    return bool(os.getenv('STRIPE_SECRET_KEY')) and bool(acc.get('stripe_customer')) and (acc.get('plan_period') or '1') == '1'


def offer(acc: dict, *, plan: dict | None) -> dict | None:
    """The offer this account may take, or None (already used, no running bot, not a paying customer...)."""
    if acc.get('retention_used_at') or not plan or not acc.get('render_service_id'):
        return None
    return {'bonus': BONUS, 'discount': DISCOUNT_PCT if discount_possible(acc) else 0, 'from': int(plan['conversations']),
            'to': int(plan['conversations']) + BONUS}


def apply_stay_discount(customer_id: str) -> None:
    """DISCOUNT_PCT % off the customer's next invoice (one-time coupon on their running subscription). Raises on any failure,
    so a half-delivered offer is never recorded as taken."""
    import stripe
    key = os.environ['STRIPE_SECRET_KEY']
    try:
        stripe.Coupon.retrieve(COUPON_ID, api_key=key)
    except stripe.InvalidRequestError:
        stripe.Coupon.create(id=COUPON_ID, percent_off=DISCOUNT_PCT, duration='once', name='Zostań z Winq: -30% na następną płatność', api_key=key)
    subs = stripe.Subscription.list(customer=customer_id, status='all', limit=10, api_key=key)
    live = next((s for s in subs.data if s['status'] in ('active', 'trialing')), None)
    if not live:
        raise RuntimeError('no running subscription to discount')
    keep = [{'coupon': d['coupon']['id']} for d in (live.get('discounts') or []) if isinstance(d, dict) and d.get('coupon')]
    if any(d['coupon'] == COUPON_ID for d in keep):
        return  # already applied (a retry after a half-finished attempt)
    stripe.Subscription.modify(live['id'], discounts=keep + [{'coupon': COUPON_ID}], api_key=key)
