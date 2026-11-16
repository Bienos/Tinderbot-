"""Conversation strategy: where the chat is and which single move moves it toward meeting.

Deterministic and cheap (no model call), so it runs for every thread on every dashboard refresh.
Evidence it is built on (see the docs in the PR / chat):
- follow-up questions increase liking (Huang et al., 2017) -> react to her specific message, ask follow-ups;
- online daters who meet without a long pen-pal phase report better first impressions (Ramirez et al., 2015)
  -> invite once interest is visible instead of chatting indefinitely;
- invitations on Tinder are prepared by "testing the waters" and built on shared context (Andersen, 2024)
  -> light, concrete, easy to decline, tied to a topic you already share;
- refusals and hesitation override any goal: never push.
"""
from __future__ import annotations

import re
from datetime import datetime
from statistics import median

DEFAULT_DATE_IDEAS = [
    'kawa albo matcha na mieście',
    'spacer z kawą na wynos',
    'piwo albo wino w luźnym barze',
    'wystawa, targi albo coś w tym stylu',
    'planszówki w barze',
    'lody albo gofry i spacer',
]
DEFAULT_AVAILABILITY = 'zwykle wieczory w tygodniu, w weekend elastycznie'

MEET_WORDS = re.compile(r"\b(spotka\w*|wyj[śs]\w*|kaw\w*|piw\w*|win[oa]\w*|drink\w*|randk\w*|zobaczy\w*\s+si[eę]|"
                        r"kiedy\s+(masz|jeste)\w*|woln\w*|czas\s+w|weekend\w*|sobot\w*|niedziel\w*|piątek|piatek|"
                        r"meet\w*|coffee|drinks?|grab\b|free\s+(on|this)|weekend|date)\b", re.I)
INVITE_FROM_YOU = re.compile(r"\b(może|moze|chcesz|daj si[eę]|wyskoczymy|skoczymy|spotkajmy|umówmy|umowmy|"
                             r"wpadniemy|pójdziemy|pojdziemy|let'?s|want to|wanna|grab)\b.*\b(kaw\w*|piw\w*|win\w*|"
                             r"spacer\w*|spotka\w*|wyj[śs]\w*|drink\w*|coffee|drinks?|walk|meet\w*|lody|gofr\w*|wystaw\w*)", re.I)
DECLINE = re.compile(r"\b(nie\s+mog\w*|nie\s+dam\s+rady|nie\s+mam\s+czasu|raczej\s+nie|nie\s+teraz|może\s+kiedy[śs]|"
                     r"moze\s+kiedys|nie\s+wiem\s+czy|zobaczymy|odpada|busy|can'?t|not\s+(now|sure)|maybe\s+later)\b", re.I)
ACCEPT = re.compile(r"\b(chętnie|chetnie|jasne|pewnie|czemu\s+nie|brzmi\s+(dobrze|super|spoko)|okej|ok|spoko|pasuje|"
                    r"tak\b|sure|sounds\s+good|why\s+not|yes|down)\b", re.I)
LAUGH = re.compile(r"\b(xd+|haha\w*|hah\w*|hehe\w*|lol|😂|🤣)\b|[😂🤣😄😆😅]", re.I)
STOP_SIGNAL = re.compile(r"\b(nie\s+pisz|nie\s+jestem\s+zainteres|mam\s+chłopaka|mam\s+chlopaka|not\s+interested|"
                         r"stop\s+messaging|leave\s+me)\b", re.I)

PACE = {'slow': (7, 18), 'normal': (5, 12), 'fast': (3, 8)}  # (min exchanges before inviting, max before forcing the question)

STAGE_LABEL = {'opening': 'Otwarcie', 'rapport': 'Budowanie', 'invite': 'Okno na zaproszenie',
               'awaiting_answer': 'Czeka na odpowiedź', 'logistics': 'Ustalanie spotkania', 'date_set': 'Spotkanie ustalone',
               'cooldown': 'Po odmowie', 'fading': 'Wygasa', 'closed': 'Zamknięta'}
MOVE_LABEL = {'opener_by_owner': 'Napisz pierwszą wiadomość sam', 'react_and_follow_up': 'Zareaguj i dopytaj',
              'share_about_you': 'Powiedz coś o sobie', 'invite': 'Zaproponuj spotkanie',
              'ask_instagram': 'Zaproponuj przejście na Instagram', 'settle_details': 'Ustal dzień, godzinę i miejsce',
              'confirm_lightly': 'Potwierdź luźno, bez nowych planów', 'keep_it_light': 'Luźno, bez naciskania',
              'wait': 'Poczekaj na jej odpowiedź', 'let_go': 'Odpuść', 'stop': 'Nie pisz'}


def _ts(m):
    try:
        return datetime.fromisoformat(str(m.get('created_at', '')).replace('Z', '+00:00'))
    except ValueError:
        return None


def analyze(history, settings: dict | None = None, outcomes: list | None = None) -> dict:
    cfg = settings or {}
    goal = cfg.get('goal', 'date')
    allow_ig = cfg.get('allow_instagram', True)
    min_ex, max_ex = PACE.get(cfg.get('pace', 'normal'), PACE['normal'])
    kinds = {o.get('kind') for o in (outcomes or [])}
    hist = list(history or [])
    hers = [m for m in hist if m['sender'] == 'them']
    mine = [m for m in hist if m['sender'] == 'you']
    turns = [m['sender'] for i, m in enumerate(hist) if i == 0 or hist[i - 1]['sender'] != m['sender']]
    exchanges = min(turns.count('you'), turns.count('them'))  # back-and-forth rounds, not raw message count

    signals, score = [], 50
    recent_hers, recent_mine = hers[-6:], mine[-6:]
    if recent_hers:
        q = sum('?' in m['body'] for m in recent_hers)
        if q:
            score += min(20, 8 * q); signals.append(f'zadaje pytania ({q})')
        else:
            score -= 10; signals.append('nie zadaje pytań')
        her_len = median(len(m['body']) for m in recent_hers)
        my_len = median(len(m['body']) for m in recent_mine) if recent_mine else her_len
        ratio = her_len / max(1, my_len)
        if ratio >= 0.9:
            score += 10; signals.append('pisze tyle co Ty albo więcej')
        elif ratio < 0.5:
            score -= 15; signals.append('odpisuje dużo krócej niż Ty')
        if any(LAUGH.search(m['body']) for m in recent_hers):
            score += 8; signals.append('śmieje się / żartuje')
        if any(MEET_WORDS.search(m['body']) for m in recent_hers):
            score += 15; signals.append('sama wspomina wyjścia lub czas')
    delays = []
    for i in range(1, len(hist)):
        if hist[i]['sender'] == 'them' and hist[i - 1]['sender'] == 'you':
            a, b = _ts(hist[i - 1]), _ts(hist[i])
            if a and b:
                delays.append((b - a).total_seconds() / 3600)
    if len(delays) >= 2:
        d = median(delays[-5:])
        if d <= 2:
            score += 8; signals.append('odpisuje szybko')
        elif d >= 24:
            score -= 10; signals.append('odpisuje po ponad dobie')
    score = max(0, min(100, score))

    last = hist[-1] if hist else None
    my_invites = [i for i, m in enumerate(hist) if m['sender'] == 'you' and INVITE_FROM_YOU.search(m['body'])]
    last_invite = my_invites[-1] if my_invites else None
    after_invite = [m for m in hist[last_invite + 1:] if m['sender'] == 'them'] if last_invite is not None else []
    declined = bool(after_invite and DECLINE.search(after_invite[0]['body']) and not ACCEPT.search(after_invite[0]['body'][:25]))
    accepted = bool(after_invite and ACCEPT.search(after_invite[0]['body']) and not declined)
    exchanges_since_invite = sum(1 for m in hist[last_invite + 1:] if m['sender'] == 'them') if last_invite is not None else 0

    def out(stage, move, why):
        return {'stage': stage, 'stage_label': STAGE_LABEL[stage], 'move': move, 'move_label': MOVE_LABEL[move],
                'why': why, 'interest': score, 'signals': signals, 'exchanges': exchanges,
                'goal': goal, 'allow_instagram': allow_ig}

    if hers and STOP_SIGNAL.search(hers[-1]['body']):
        return out('closed', 'stop', 'Wyraźnie zamknęła temat. Nie piszemy.')
    if not hist:
        return out('opening', 'opener_by_owner', 'Brak wiadomości. Napisz pierwsze zdanie sam albo poproś agenta; najlepiej z czegoś z jej profilu.')
    if kinds & {'date_confirmed'}:
        return out('date_set', 'confirm_lightly', 'Spotkanie potwierdzone. Tylko luźna rozmowa i ewentualne szczegóły.')
    if 'date_cancelled' in kinds and not kinds & {'date_confirmed'}:
        return out('cooldown', 'keep_it_light', 'Spotkanie odwołane. Bez od razu nowej propozycji; niech ona zaproponuje termin albo wrócimy do tego później.')
    if kinds & {'date_tentative', 'date_suggested'} or accepted:
        return out('logistics', 'settle_details', 'Jest zgoda albo wstępna propozycja. Domknij konkretny dzień, godzinę i miejsce.')
    if last and last['sender'] == 'you':
        return out('awaiting_answer', 'wait', 'Ostatnia wiadomość jest Twoja. Nie dopisujemy kolejnej.')
    if declined:
        if exchanges_since_invite < 4:
            if allow_ig and 'instagram_shared' not in kinds and score >= 55 and 'może kiedy' in after_invite[0]['body'].lower():
                return out('cooldown', 'ask_instagram', 'Odłożyła spotkanie na „kiedyś", ale rozmowa jest ciepła. Instagram to lżejszy krok.')
            return out('cooldown', 'keep_it_light', 'Niedawno odmówiła albo się wahała. Zero nacisku, wracamy do luźnej rozmowy.')
        if len(my_invites) >= 2:
            return out('cooldown', 'keep_it_light', 'Były już dwie propozycje. Kolejną może zaproponować ona.')
    if score < 30 and exchanges >= 3:
        return out('fading', 'let_go' if score < 20 else 'keep_it_light', 'Słabe sygnały zainteresowania. Krótko i bez pytań albo odpuść.')
    wants_meet = any(MEET_WORDS.search(m['body']) for m in hers[-2:])
    invite_ready = (wants_meet and exchanges >= 2) or (exchanges >= min_ex and score >= 60) or (exchanges >= max_ex and score >= 45)
    if goal in ('date', 'date_or_instagram') and invite_ready and (last_invite is None or exchanges_since_invite >= 4):
        why = 'Sama wspomniała o wyjściu.' if wants_meet else (
            'Dobre sygnały i kilka wymian: czas na lekką propozycję.' if score >= 60 else
            'Rozmowa trwa już długo. Lepiej zaproponować spotkanie niż ciągnąć czat.')
        return out('invite', 'invite', why)
    if goal == 'instagram' and invite_ready and allow_ig and 'instagram_shared' not in kinds:
        return out('invite', 'ask_instagram', 'Dobre sygnały: zaproponuj Instagram.')
    my_last = mine[-1]['body'] if mine else ''
    if my_last.rstrip().endswith('?'):
        return out('rapport', 'share_about_you', 'Ostatnio pytałeś Ty. Teraz odpowiedz i daj coś od siebie, bez kolejnego przesłuchania.')
    return out('rapport', 'react_and_follow_up', 'Budujecie relację. Odnieś się do tego, co napisała, i dopytaj o szczegół.')


def planning_facts(settings: dict) -> dict:
    """Owner-approved planning facts added to the verified profile so invitations stay truthful."""
    ideas = settings.get('date_ideas') or DEFAULT_DATE_IDEAS
    return {'dostępność': settings.get('availability') or DEFAULT_AVAILABILITY,
            'pomysły_na_spotkanie': '; '.join(ideas)}
