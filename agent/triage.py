"""Small, deterministic conversation state projection.

Conversation turn-taking is orthogonal to milestones (Instagram/date) and
source availability. No inference of rejection from inactivity.
This module never operates a third-party service.
"""
from __future__ import annotations
from typing import Sequence


def project(thread: dict, messages: Sequence[dict], drafts: Sequence[dict],
            notifications: Sequence[dict]) -> dict:
    latest = messages[-1] if messages else None
    user_paused = bool(thread.get('user_paused', 0))
    user_archived = bool(thread.get('user_archived', 0))
    visibility = thread.get('source_visibility', 'available')
    pending = [d for d in drafts if d['status'] == 'pending']
    pending_current = bool(latest and any(d['anchor_message_id'] == latest['id'] for d in pending))
    kinds = sorted(set(n['kind'] for n in notifications))

    # Separate factual conversation lifecycle from social outcomes.
    if user_archived:
        state, reason = 'archived', 'Archiwizacja przez użytkownika, nie stan konta na platformie.'
    elif not thread.get('source_seen', 1):
        state, reason = 'not_synced', 'Nie sprawdzono jeszcze listy dopasowań.'
    elif visibility != 'available':
        state, reason = 'unavailable_unknown', 'Brak pewnego dostępu do rozmowy. Nie zakładaj unmatch.'
    elif user_paused:
        state, reason = 'paused', 'Użytkownik wstrzymał obsługę.'
    elif latest is None:
        state, reason = 'new_match', 'Dopasowanie widoczne, ale bez wiadomości.'
    elif latest['sender'] == 'them':
        state, reason = 'needs_reply', 'Ostatnia wiadomość pochodzi od drugiej osoby.'
    elif latest['sender'] == 'you':
        state, reason = 'waiting', 'Ostatnia wiadomość pochodzi od użytkownika.'
    else:
        state, reason = 'needs_review', 'Nieznany nadawca ostatniej wiadomości.'

    if pending_current and state == 'needs_reply':
        next_action = 'review_draft'
    elif state == 'needs_reply':
        next_action = 'prepare_draft'
    elif state == 'new_match':
        next_action = 'inspect_profile'  # cannot fabricate an opener from no profile context
    else:
        next_action = 'no_action'

    return {
        **thread, 'state': state, 'state_reason': reason, 'next_action': next_action,
        'message_count': len(messages), 'latest_message': latest['body'] if latest else None,
        'latest_sender': latest['sender'] if latest else None,
        'latest_message_id': latest['id'] if latest else None,
        'outcomes': kinds, 'pending_draft_count': len(pending),
        'has_current_draft': pending_current,
    }
