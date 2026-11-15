from agent.triage import project
from agent.storage import set_thread_flags, sync_visible_threads, connect, init_db, threads
from agent.engine import should_draft
import os
import pytest


def m(i,sender,body='hi'):
    return {'id':i,'sender':sender,'body':body}


def t(**overrides):
    return {'id':'t1','display_name':'Fictional','source_visibility':'available',
            'user_archived':0,'user_paused':0,**overrides}


def test_new_match_and_turns():
    assert project(t(),[],[],[])['state']=='new_match'
    assert project(t(),[m('x','them')],[],[])['state']=='needs_reply'
    assert project(t(),[m('x','them'),m('y','you')],[],[])['state']=='waiting'


def test_unknown_is_not_unmatch_and_pause_override():
    assert project(t(source_visibility='not_observed'),[m('x','them')],[],[])['state']=='unavailable_unknown'
    assert project(t(user_paused=1),[m('x','them')],[],[])['state']=='paused'
    assert project(t(user_archived=1),[m('x','them')],[],[])['state']=='archived'


def test_social_outcomes_are_independent_of_reply_state():
    x=project(t(),[m('a','them','insta: @abc')],[],[{'kind':'instagram_shared'}])
    assert x['state']=='needs_reply' and x['outcomes']==['instagram_shared']


def test_pending_draft_is_not_action_if_stale():
    draft={'status':'pending','anchor_message_id':'old'}
    p=project(t(),[m('new','them')],[draft],[])
    assert p['next_action']=='prepare_draft'
    assert p['pending_draft_count']==1
    draft['anchor_message_id']='new'
    assert project(t(),[m('new','them')],[draft],[])['next_action']=='review_draft'


def test_last_message_only_from_user_is_waiting_even_after_days():
    assert project(t(),[m('a','you','I sent yesterday')],[],[])['state']=='waiting'
    assert not should_draft([{'sender':'you','body':'I sent yesterday'}])
