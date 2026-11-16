"""Deterministic resource budgets, separate from the conversational model."""
import os,time
from agent import storage as s
class BudgetExceeded(Exception):pass

def integer(name,default,minimum=1,maximum=100000):
    try:return max(minimum,min(maximum,int(os.getenv(name,str(default)))))
    except ValueError:return default

def claim_model_call():
    now=time.time();cap=integer('MODEL_CALLS_PER_MINUTE',30)
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM model_calls WHERE ts<?',(now-3600,))
        if db.execute('SELECT COUNT(*) FROM model_calls WHERE ts>?',(now-60,)).fetchone()[0]>=cap:
            raise BudgetExceeded('Model call budget exceeded')
        db.execute('INSERT INTO model_calls(ts) VALUES(?)',(now,))

def check_send_budget(db,thread_id):
    now=time.time();active="status IN ('sending','sent','uncertain') AND updated>?"
    if db.execute('SELECT COUNT(*) FROM actions WHERE thread_id=? AND '+active,(thread_id,now-3600)).fetchone()[0]>=integer('AUTO_SENDS_PER_THREAD_HOUR',60):
        raise BudgetExceeded('Conversation hourly send limit reached')
    if db.execute('SELECT COUNT(*) FROM actions WHERE '+active,(now-3600,)).fetchone()[0]>=integer('AUTO_SENDS_TOTAL_PER_HOUR',200):
        raise BudgetExceeded('Account hourly send limit reached')

    thread=db.execute('SELECT platform FROM threads WHERE id=?',(thread_id,)).fetchone()
    if thread and thread['platform']=='tinder':
        active="a.status IN ('sending','sent','uncertain') AND a.updated>?"
        if db.execute('SELECT COUNT(*) FROM actions a WHERE a.thread_id=? AND '+active,(thread_id,now-3600)).fetchone()[0]>=integer('TINDER_SENDS_PER_THREAD_HOUR',10):
            raise BudgetExceeded('Tinder conversation hourly send budget reached')
        for seconds,name,default in ((3600,'TINDER_SENDS_PER_HOUR',20),(86400,'TINDER_SENDS_PER_DAY',100)):
            count=db.execute("SELECT COUNT(*) FROM actions a JOIN threads t ON t.id=a.thread_id WHERE t.platform='tinder' AND "+active,(now-seconds,)).fetchone()[0]
            if count>=integer(name,default):raise BudgetExceeded('Tinder account send budget reached')


def tinder_sends_since(seconds):
    """Verified or possibly delivered Tinder sends in the last N seconds (the same count the send budgets use)."""
    with s.connect() as db:
        return db.execute("SELECT COUNT(*) FROM actions a JOIN threads t ON t.id=a.thread_id WHERE t.platform='tinder' "
                          "AND a.status IN ('sending','sent','uncertain') AND a.updated>?",(time.time()-seconds,)).fetchone()[0]
