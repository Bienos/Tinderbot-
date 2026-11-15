import json
from agent.strategy import analyze, planning_facts


def conv(*pairs):
    return [{'sender':s,'body':b} for s,b in pairs]


WARM=[('you','hej, te zdjęcia z Tatr to Kasprowy?'),('them','tak! byłeś kiedyś? 😄'),
      ('you','raz, zimą, prawie zamarzłem'),('them','hahah to klasyka, ja wolę latem, a ty co lubisz robić?'),
      ('you','ostatnio dużo biegam i gotuję'),('them','o, co gotujesz najczęściej?'),
      ('you','curry, mam fazę'),('them','mega, ja uwielbiam tajskie, znasz jakieś dobre miejsce?'),
      ('you','mam jedno ulubione'),('them','hahah tajemniczy jesteś, zdradzisz?')]


def test_new_chat_builds_rapport_with_follow_up():
    p=analyze(conv(('you','hej'),('them','hej, co tam?')),{})
    assert p['stage']=='rapport' and p['move'] in ('react_and_follow_up','share_about_you')


def test_warm_chat_after_enough_rounds_invites():
    p=analyze(conv(*WARM),{'pace':'normal'})
    assert p['move']=='invite' and p['interest']>=60


def test_she_mentions_meeting_triggers_invite_early():
    p=analyze(conv(('you','hej'),('them','hej :)'),('you','jak weekend?'),('them','spoko, może w końcu wyjdę gdzieś na kawę')),{})
    assert p['move']=='invite'


def test_decline_means_no_pressure():
    h=WARM+[('you','może kawa w czwartek wieczorem?'),('them','w tym tygodniu nie dam rady, sorry')]
    p=analyze(conv(*h),{})
    assert p['move'] in ('keep_it_light','ask_instagram') and p['stage']=='cooldown'


def test_maybe_later_with_warm_chat_offers_instagram_when_allowed():
    h=WARM+[('you','może kawa w czwartek wieczorem?'),('them','może kiedyś, teraz mam zawał w pracy haha')]
    assert analyze(conv(*h),{'allow_instagram':True})['move']=='ask_instagram'
    assert analyze(conv(*h),{'allow_instagram':False})['move']=='keep_it_light'


def test_acceptance_moves_to_details_and_confirmed_date_stays_light():
    h=WARM+[('you','może kawa w czwartek wieczorem?'),('them','chętnie! o której?')]
    assert analyze(conv(*h),{})['move']=='settle_details'
    assert analyze(conv(*h),{},[{'kind':'date_confirmed'}])['move']=='confirm_lightly'


def test_cancelled_date_does_not_reinvite_immediately():
    assert analyze(conv(*WARM),{},[{'kind':'date_cancelled'}])['move']=='keep_it_light'


def test_waits_when_last_message_is_ours_and_stops_on_boundary():
    assert analyze(conv(('them','hej'),('you','hej!')),{})['move']=='wait'
    assert analyze(conv(('you','hej'),('them','nie pisz do mnie więcej')),{})['move']=='stop'


def test_low_interest_does_not_push():
    h=[('you','hej, jak minął dzień? co dziś robiłaś ciekawego?'),('them','ok'),('you','a jakie masz plany na weekend, coś fajnego?'),
       ('them','nie wiem'),('you','lubisz góry czy bardziej morze? ja zdecydowanie góry'),('them','morze')]
    assert analyze(conv(*h),{})['move'] in ('keep_it_light','let_go')


def test_pace_changes_invite_timing():
    h=WARM[:6]
    assert analyze(conv(*h),{'pace':'fast'})['move']=='invite'
    assert analyze(conv(*h),{'pace':'slow'})['move']!='invite'


def test_chat_only_goal_never_invites():
    assert analyze(conv(*WARM),{'goal':'chat'})['move']!='invite'


def test_planning_facts_have_defaults():
    f=planning_facts({})
    assert 'wieczory' in f['dostępność'] and 'kawa' in f['pomysły_na_spotkanie']


def test_corpus_boundaries_never_get_details_or_instagram_push():
    for line in open('data/full_conversations_augment.jsonl',encoding='utf-8'):
        c=json.loads(line)
        if c['expected_outcome'] not in ('boundary','low_engagement'):continue
        h=[{'sender':'you' if t['speaker']=='user' else 'them','body':t['text']} for t in c['turns']]
        assert analyze(h,{})['move'] not in ('settle_details','ask_instagram'),c['id']


def test_plan_reaches_model_and_wait_skips_model(store,monkeypatch):
    import json as j
    from agent import engine
    calls=[]
    def fake(prompt,encoded,schema,cached_system=None):
        calls.append(j.loads(encoded));return j.dumps({'action':'no_reply','reply':'','note':'x','claims':[]}),1,1
    monkeypatch.setattr(engine,'configured',lambda:True);monkeypatch.setattr(engine,'complete',fake)
    h=conv(*WARM)
    engine.generate(h,{},plan=analyze(h,{}))
    assert calls[-1]['conversation_plan']['move']=='invite'
    n=len(calls);d,g=engine.generate(h,{},plan={'move':'wait','why':'x'})
    assert len(calls)==n and d.action=='no_reply'


def test_legacy_default_settings_upgrade_but_owner_values_stay(store):
    import json as j
    from agent import runtime as rt, storage as s
    with s.connect() as db:
        db.execute('UPDATE settings SET value=? WHERE id=1',(j.dumps({**rt.DEFAULTS,'style':rt.LEGACY_STYLE,'date_ideas':[],'retention_days':30,'language':'pl'}),))
    cfg=rt.settings()
    assert cfg['style']==rt.DEFAULT_STYLE and cfg['date_ideas']==rt.DEFAULT_DATE_IDEAS and cfg['retention_days']==365
    assert cfg['language']=='pl'
    with s.connect() as db:
        db.execute('UPDATE settings SET value=? WHERE id=1',(j.dumps({**rt.DEFAULTS,'style':'mój własny styl'}),))
    assert rt.settings()['style']=='mój własny styl'
