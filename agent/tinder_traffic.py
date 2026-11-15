"""Conservative traffic management. No disguising identity or bypassing account restrictions."""
import hashlib,json,math,time
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from agent import storage as s
from agent.limits import integer

class TrafficBudget(Exception):
    def __init__(self,delay):self.delay=delay

def retry_after(value,default=300):
    """RFC 9110 supports either delta-seconds or an HTTP date; never shorten the wait."""
    try:
        if value is None:return default
        if str(value).strip().isdigit():
            if len(str(value).strip())>8:raise OverflowError()
            seconds=int(value)
        else:
            date=parsedate_to_datetime(str(value))
            if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
            seconds=math.ceil(date.timestamp()-time.time())
        # Excessive/unrepresentable values require a manual stop instead of an early retry.
        if seconds>31536000:raise OverflowError()
        return max(15,seconds)
    except (ValueError,TypeError):return default

def import_phase():
    """True until the first complete sync of the current Tinder connection has finished."""
    for row in s.rows("SELECT value FROM connections WHERE id LIKE 'tinder:%' AND enabled=1"):
        if not json.loads(row['value']).get('initial_import_done'):return True
    return False

def caps():
    """Higher budget once, for the first full import; conservative budget for everyday syncing afterwards."""
    minute,hour=integer('TINDER_REQUESTS_PER_MINUTE',30),integer('TINDER_REQUESTS_PER_HOUR',300)
    if import_phase():
        minute=max(minute,integer('TINDER_IMPORT_REQUESTS_PER_MINUTE',120));hour=max(hour,integer('TINDER_IMPORT_REQUESTS_PER_HOUR',1000))
    return [(60,minute),(3600,hour)]

def claim_request():
    now=time.time()
    caps_now=caps()
    with s.connect() as db:
        db.execute('BEGIN IMMEDIATE');db.execute('DELETE FROM tinder_requests WHERE ts<?',(now-3600,))
        for window,cap in caps_now:
            rows=db.execute('SELECT ts FROM tinder_requests WHERE ts>? ORDER BY ts',(now-window,)).fetchall()
            if len(rows)>=cap:raise TrafficBudget(max(15,math.ceil(rows[0]['ts']+window-now)))
        db.execute('INSERT INTO tinder_requests(ts) VALUES(?)',(now,))

def metadata_key(match):
    # Use activity metadata only as a cache hint, never as sufficient freshness to send.
    fields={k:match[k] for k in ('last_activity_date','message_count','last_message_id','messages') if k in match}
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest() if fields else None

def should_read(thread,cached,key,now=None):
    now=time.time() if now is None else now
    if thread['user_paused'] or thread['user_archived']:return False
    if not cached or not cached.get('last_read'):return True
    if key and cached.get('activity_key')!=key:return True
    if thread.get('source_visibility')!='available':return True
    grants=s.rows('SELECT * FROM grants WHERE thread_id=?',(thread['id'],))
    active=bool(grants and all(grants[0][k] for k in ('enabled','participant_consent','disclosed')))
    # Active threads are refreshed on each scheduled poll when metadata is missing/unreliable.
    if active:return True
    return now-cached['last_read']>=integer('TINDER_INACTIVE_THREAD_REFRESH',3600,60,86400)
