import json
from pathlib import Path
from agent.engine import prepare_context, should_draft
from agent.outcomes import detect, date_outcomes, instagram_outcomes
from agent.browser import assert_allowed
import pytest

def m(sender, text): return {'sender':sender,'body':text}

def test_context_window_defaults_to_40_and_is_configurable(monkeypatch):
    hist=[m('them',f'message{i}') for i in range(60)]
    context=prepare_context(hist)
    assert len(context['recent_messages'])==40
    assert context['recent_messages'][0]['text']=='message20'
    assert context['recent_messages'][-1]['text']=='message59'
    monkeypatch.setenv('CONTEXT_MESSAGES','14')
    assert prepare_context(hist)['recent_messages'][0]['text']=='message46'

def test_draft_only_when_their_message_is_latest():
    assert should_draft([m('them','hello')])
    assert not should_draft([m('them','hi'),m('you','hi')])

def test_instagram_requires_explicitly_shared_handle():
    assert not instagram_outcomes([m('them','jestem na insta')])
    assert not instagram_outcomes([m('you','mój insta @fake_only')])
    out=instagram_outcomes([m('them','insta: @ola_demo_fikcyjna')])
    assert out[0].kind=='instagram_shared'
    assert out[0].fingerprint=='ola_demo_fikcyjna'

def test_date_requires_mutual_matching_specifics():
    propose=m('you','2026-11-20 o 19:00, miejsce: Kawiarnia Demo')
    assent=m('them','tak, 2026-11-20 19:00, miejsce: Kawiarnia Demo pasuje')
    assert date_outcomes([propose,assent])[0].kind=='date_confirmed'
    assert all(o.kind != 'date_confirmed' for o in date_outcomes([propose,m('them','może jakoś w przyszłym tygodniu')]))
    assert all(o.kind != 'date_confirmed' for o in date_outcomes([propose,m('them','nie, 2026-11-20 19:00, miejsce: Kawiarnia Demo')]))
    assert all(o.kind != 'date_confirmed' for o in date_outcomes([propose,m('them','tak, 2026-11-21 19:00, miejsce: Kawiarnia Demo')]))

def test_browser_rejects_unapproved_targets():
    with pytest.raises(PermissionError): assert_allowed('https://tinder.com/app/messages')
    with pytest.raises(PermissionError): assert_allowed('file:///etc/passwd')
    assert_allowed('http://127.0.0.1:8765/mock')

def test_scenario_suite_has_300_synthetic_cases():
    file=Path(__file__).resolve().parent.parent/'data'/'scenarios_300.jsonl'
    lines=file.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines)==300
    ids=set()
    for line in lines:
        case=json.loads(line)
        assert case['origin'].startswith('synthetic')
        assert case['incoming_message']
        ids.add(case['id'])
    assert len(ids)==300
