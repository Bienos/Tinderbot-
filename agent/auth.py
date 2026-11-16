"""Single-owner credentials and revocable, expiring dashboard sessions."""
import hashlib
import os
import secrets
import stat
import time
from pathlib import Path

def valid_secret(value):
    return isinstance(value,str) and 24 <= len(value) <= 256 and value.isascii() and all(32 < ord(c) < 127 for c in value)

def token():
    configured=os.getenv('DASHBOARD_TOKEN','')
    if configured:
        if not valid_secret(configured):raise RuntimeError('DASHBOARD_TOKEN must be 24–256 printable ASCII characters without spaces')
        return configured
    from agent.storage import DB_PATH
    p=DB_PATH.parent/'dashboard-token'
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:pass
    else:
        with os.fdopen(fd,'w') as f:
            f.write(secrets.token_urlsafe(32));f.flush();os.fsync(f.fileno())
    try:
        fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'r') as f:
            metadata=os.fstat(f.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.getuid() or metadata.st_mode & 0o077:
                raise RuntimeError('Dashboard token must be a regular owner-only file')
            value=f.read(257).strip()
    except OSError:raise RuntimeError('Cannot read a safe dashboard token file') from None
    if not valid_secret(value):raise RuntimeError('Dashboard token file is empty or invalid; replace it before starting')
    return value

def same_secret(value,expected):
    return isinstance(value,str) and isinstance(expected,str) and value.isascii() and expected.isascii() and secrets.compare_digest(value,expected)

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def create_session():
    from agent import storage as s
    session=secrets.token_urlsafe(32);now=time.time()
    with s.connect() as db:
        db.execute('DELETE FROM sessions WHERE expires<=?',(now,))
        db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(session),digest(token()),now+43200))
        db.execute('DELETE FROM sessions WHERE id NOT IN (SELECT id FROM sessions ORDER BY expires DESC LIMIT 20)')
    return session

def session_valid(value):
    from agent import storage as s
    if not valid_secret(value):return False
    r=s.rows('SELECT * FROM sessions WHERE id=?',(digest(value),))
    return bool(r and r[0]['expires']>time.time() and same_secret(r[0]['owner_hash'],digest(token())))

def revoke_session(value):
    from agent import storage as s
    if valid_secret(value):
        with s.connect() as db:db.execute('DELETE FROM sessions WHERE id=?',(digest(value),))


def verify_sso(value,audience):
    """Accept a control-plane sign-in token once: valid HMAC, our origin as audience, not expired, unused nonce."""
    import base64,hmac,json
    from agent import storage as s
    secret=os.getenv('SSO_SECRET','')
    if len(secret)<32 or not isinstance(value,str) or len(value)>2000 or value.count('.')!=1:return False
    payload,sig=value.split('.')
    pad=lambda x:x+'='*(-len(x)%4)
    try:
        expected=hmac.new(secret.encode(),payload.encode(),hashlib.sha256).digest()
        if not hmac.compare_digest(expected,base64.urlsafe_b64decode(pad(sig))):return False
        data=json.loads(base64.urlsafe_b64decode(pad(payload)))
    except (ValueError,TypeError):return False
    now=time.time()
    if data.get('aud','').rstrip('/')!=audience.rstrip('/') or not (now-5<data.get('exp',0)<=now+65):return False
    nonce=str(data.get('n',''))
    if not 16<=len(nonce)<=64:return False
    with s.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS sso_nonces (nonce TEXT PRIMARY KEY, expires REAL NOT NULL)')
        db.execute('DELETE FROM sso_nonces WHERE expires<?',(now,))
        if db.execute('SELECT 1 FROM sso_nonces WHERE nonce=?',(nonce,)).fetchone():return False
        db.execute('INSERT INTO sso_nonces VALUES(?,?)',(nonce,now+120))
    return True


def verify_control_request(ts,sig,audience,purpose):
    """A read-only request from the control service, signed with this instance's SSO_SECRET.
    Signature = HMAC-SHA256(secret, "<purpose>:<unix seconds>:<our origin>"), valid for two minutes either side.
    Replays inside that window can only read the same aggregate numbers again."""
    import hmac
    secret=os.getenv('SSO_SECRET','')
    if len(secret)<32 or not isinstance(ts,str) or not isinstance(sig,str) or len(ts)>12 or len(sig)>128:return False
    try:stamp=int(ts)
    except ValueError:return False
    if abs(time.time()-stamp)>120:return False
    expected=hmac.new(secret.encode(),f"{purpose}:{stamp}:{audience.rstrip('/')}".encode(),hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,sig.lower())
