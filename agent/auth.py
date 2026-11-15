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
