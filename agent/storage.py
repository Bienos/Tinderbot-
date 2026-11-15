from __future__ import annotations
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path(os.getenv('AGENT_DB_PATH', str(Path(__file__).resolve().parent.parent / 'runtime' / 'agent.db')))

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try: return super().__exit__(*args)
        finally: self.close()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(str(DB_PATH), timeout=20, factory=ClosingConnection)
    DB_PATH.chmod(0o600)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    return db

def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS threads (
          id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
          user_paused INTEGER NOT NULL DEFAULT 0,
          user_archived INTEGER NOT NULL DEFAULT 0,
          source_visibility TEXT NOT NULL DEFAULT 'available',
          source_seen INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS source_messages (
          id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, sender TEXT NOT NULL,
          body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, sender TEXT NOT NULL,
          body TEXT NOT NULL, created_at TEXT NOT NULL, synced_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS drafts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
          anchor_message_id TEXT NOT NULL, body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', generator TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(thread_id, anchor_message_id));
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL,
          kind TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(thread_id, kind, fingerprint));
        CREATE INDEX IF NOT EXISTS idx_msgs_thread ON messages(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_src_thread ON source_messages(thread_id, created_at);
        ''')
        # Non-destructive migration for existing prototype SQLite files.
        cols = {r[1] for r in db.execute('PRAGMA table_info(threads)').fetchall()}
        for name, definition in (
            ('user_paused', 'INTEGER NOT NULL DEFAULT 0'),
            ('user_archived', 'INTEGER NOT NULL DEFAULT 0'),
            ('source_visibility', "TEXT NOT NULL DEFAULT 'available'"),
            ('source_seen', 'INTEGER NOT NULL DEFAULT 0'),
        ):
            if name not in cols:
                db.execute(f'ALTER TABLE threads ADD COLUMN {name} {definition}')
        if db.execute('SELECT COUNT(*) FROM threads').fetchone()[0] == 0 and os.getenv('SEED_SIMULATOR','true') == 'true' and not db.execute("SELECT 1 FROM sqlite_master WHERE name='tombstones'").fetchone():
            fixtures = [
                ('t1','Kasia',[
                    ('them','hej, widzę że słuchasz techno?'),
                    ('you','tak, szczególnie groovy klimaty. a ty?'),
                    ('them','w sobotę byłam w klubie i nadal dochodzę do siebie XD')
                ]),
                ('t2','Ola',[
                    ('you','masz może insta?'),
                    ('them','jasne, mój insta to @ola_demo_fikcyjna')
                ]),
                ('t3','Lena',[
                    ('them','może kawa w przyszłym tygodniu?'),
                    ('you','proponuję 2026-11-20 o 19:00, miejsce: Kawiarnia Demo'),
                    ('them','tak, 2026-11-20 o 19:00, miejsce: Kawiarnia Demo pasuje!')
                ]),
                ('t4','Maja',[]),
                ('t5','Julia',[
                    ('them','lubisz bardziej góry czy morze?'),
                    ('you','raczej góry, ale latem trudno odmówić morzu hah')
                ]),
                ('t6','Nina',[
                    ('them','hej, co tam?'),
                    ('you','hej, właśnie wróciłem do domu. a u ciebie?'),
                    ('them','mam naprawdę fatalny dzień w pracy')
                ]),
                ('t7','Sara',[
                    ('them','spotkajmy się jutro'),
                    ('you','może, ale muszę sprawdzić kalendarz')
                ])
            ]
            fixture_start=datetime.now(timezone.utc)-timedelta(days=2)
            for thread_id, name, messages in fixtures:
                db.execute('INSERT INTO threads (id,display_name) VALUES (?,?)',(thread_id,name))
                for idx,(sender,body) in enumerate(messages):
                    db.execute('INSERT INTO source_messages VALUES (?,?,?,?,?)',
                               (f'{thread_id}-{idx+1}',thread_id,sender,body,
                                (fixture_start+timedelta(minutes=idx)).isoformat(timespec='seconds')))

def rows(sql: str, args=()):
    with connect() as db:
        return [dict(row) for row in db.execute(sql,args).fetchall()]

def threads():
    return rows('SELECT * FROM threads ORDER BY display_name')

def source_for_thread(thread_id: str):
    return rows('SELECT * FROM source_messages WHERE thread_id=? ORDER BY created_at,rowid',(thread_id,))

def messages(thread_id: str):
    return rows('SELECT * FROM messages WHERE thread_id=? ORDER BY created_at,rowid',(thread_id,))

def messages_by_thread():
    """Every thread's messages in one query, each list in the same order messages() returns it."""
    out = {}
    for m in rows('SELECT * FROM messages ORDER BY thread_id,created_at,rowid'):
        out.setdefault(m['thread_id'], []).append(m)
    return out

def sync_message(item: dict):
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO messages (id,thread_id,sender,body,created_at,synced_at) VALUES (?,?,?,?,?,?)',
                   (item['id'],item['thread_id'],item['sender'],item['body'],item['created_at'],utcnow()))

def upsert_draft(thread_id: str, anchor: str, body: str, generator: str):
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO drafts (thread_id,anchor_message_id,body,status,generator,created_at) VALUES (?,?,?,?,?,?)',
                   (thread_id,anchor,body,'pending',generator,utcnow()))

def all_drafts():
    return rows('''SELECT d.*,t.display_name FROM drafts d JOIN threads t ON t.id=d.thread_id
                ORDER BY d.id DESC''')

def draft_by_id(draft_id: int):
    result=rows('SELECT * FROM drafts WHERE id=?',(draft_id,))
    return result[0] if result else None

def set_draft_status(draft_id: int, status: str):
    with connect() as db:
        db.execute('UPDATE drafts SET status=? WHERE id=?',(status,draft_id))

def new_notification(thread_id: str, kind: str, fingerprint: str, body: str):
    with connect() as db:
        cursor = db.execute('INSERT OR IGNORE INTO notifications (thread_id,kind,fingerprint,body,created_at) VALUES (?,?,?,?,?)',
                            (thread_id,kind,fingerprint,body,utcnow()))
        return cursor.rowcount > 0

def notifications():
    return rows('''SELECT n.*,t.display_name FROM notifications n JOIN threads t ON t.id=n.thread_id
                ORDER BY n.id DESC''')

def mock_send(thread_id: str, body: str):
    # Only the local fictional conversation sandbox can be changed by this function.
    with connect() as db:
        exists = db.execute('SELECT 1 FROM threads WHERE id=?',(thread_id,)).fetchone()
        if not exists: raise KeyError(thread_id)
        ident = 'manual-' + __import__('uuid').uuid4().hex
        db.execute('INSERT INTO source_messages VALUES (?,?,?,?,?)',
                   (ident,thread_id,'you',body,utcnow()))
    return ident


def set_thread_flags(thread_id: str, *, paused=None, archived=None, visibility=None):
    updates = []
    args = []
    if paused is not None:
        updates.append('user_paused=?'); args.append(int(bool(paused)))
    if archived is not None:
        updates.append('user_archived=?'); args.append(int(bool(archived)))
    if visibility is not None:
        if visibility not in ('available', 'not_observed'):
            raise ValueError('Invalid source visibility')
        updates.append('source_visibility=?'); args.append(visibility)
    if not updates: return
    with connect() as db:
        c = db.execute('UPDATE threads SET '+', '.join(updates)+' WHERE id=?', (*args, thread_id))
        if c.rowcount == 0: raise KeyError(thread_id)


def sync_visible_threads(seen_ids: set[str]):
    """A complete fixture snapshot: absence means UNKNOWN, never unmatch.
    Production adapters must document whether their listing is complete.
    """
    with connect() as db:
        db.execute("UPDATE threads SET source_visibility='not_observed'")
        for thread_id in seen_ids:
            db.execute("UPDATE threads SET source_visibility='available', source_seen=1 WHERE id=?", (thread_id,))
