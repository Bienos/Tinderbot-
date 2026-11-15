from agent import style


def m(sender,body,i=0,thread='x'):
    return {'id':f'{thread}-{i}','sender':sender,'body':body}


def test_corpus_library_has_reply_pairs_in_both_languages():
    pairs=style.corpus_pairs()
    assert len(pairs)>300
    assert {p['lang'] for p in pairs}=={'pl','en'}
    assert all(p['them'] and p['reply'] for p in pairs)


def test_examples_match_situation_and_language(store):
    hist=[m('them','byłam w sobotę na techno i nadal dochodzę do siebie XD')]
    ex=style.select_examples(hist,k=6)
    assert 1<=len(ex)<=6
    assert all(style.language_of(e['them']+' '+e['you'])=='pl' for e in ex)
    assert len({e['you'] for e in ex})==len(ex)


def test_no_examples_without_incoming_message(store):
    assert style.select_examples([m('you','hej')])==[]


def test_own_replies_are_preferred_and_current_thread_excluded(store):
    from agent import storage as s
    with s.connect() as db:
        db.execute("INSERT INTO threads(id,display_name,platform,source_seen) VALUES('tinder:o:a','A','tinder',1)")
        db.execute("INSERT INTO threads(id,display_name,platform,source_seen) VALUES('tinder:o:b','B','tinder',1)")
        for tid,rows in (('tinder:o:a',[('them','byłam na techno w sobotę'),('you','haha i jak, żyjesz jeszcze?')]),
                         ('tinder:o:b',[('them','techno w sobotę było mocne'),('you','to zdanie z bieżącej rozmowy')])):
            for i,(sender,body) in enumerate(rows):
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',(f'{tid}:{i}',tid,sender,body,f'2026-11-1{i}T10:00:00Z','x'))
    ex=style.select_examples([m('them','w sobotę byłam na techno')],exclude_thread='tinder:o:b',k=6)
    assert ex[0]['source']=='own' and ex[0]['you']=='haha i jak, żyjesz jeszcze?'
    assert all(e['you']!='to zdanie z bieżącej rozmowy' for e in ex)


def test_canon_is_deterministic_and_large_enough_to_cache():
    a,b=style.canon_text('pl'),style.canon_text('pl')
    assert a==b and a.startswith('STYLE CANON')
    assert len(a)>2500  # comfortably above the 512-token cache minimum


def test_style_reaches_model_request(store,monkeypatch):
    import json
    from agent import engine
    seen={}
    def fake_complete(prompt,encoded,schema,cached_system=None):
        seen['ctx']=json.loads(encoded);seen['canon']=cached_system
        return json.dumps({'action':'no_reply','reply':'','note':'x','claims':[]}),1,1
    monkeypatch.setattr(engine,'configured',lambda:True)
    monkeypatch.setattr(engine,'complete',fake_complete)
    hist=[m('them','byłam na techno i nadal dochodzę do siebie')]
    ex=style.select_examples(hist,k=4)
    engine.generate(hist,{},style_examples=ex,style_stats=style.style_stats(),canon=style.canon_text('pl'))
    assert seen['ctx']['style_examples']==ex and seen['ctx']['style_stats']['samples']>0
    assert seen['canon'].startswith('STYLE CANON')
