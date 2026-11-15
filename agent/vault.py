"""Encrypted secret storage for per-customer instances.

Secrets (the customer's Tinder session token) are encrypted with AES-256-GCM before they touch the
database. The key lives only in the TOKEN_ENCRYPTION_KEY environment variable of that one instance, so a
copy of the database alone, or a copy of another customer's instance, reveals nothing. Without a key the
vault refuses to store anything (fail closed); plaintext is never written. Values never leave this module
except to the code that uses them, and they are never returned to the browser or logged.

Key rotation: set the new key in TOKEN_ENCRYPTION_KEY and the old one in TOKEN_ENCRYPTION_KEY_OLD; secrets
are re-encrypted with the new key the next time they are read.
"""
from __future__ import annotations

import base64
import binascii
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agent import storage as s

VERSION = b'v1'


class VaultUnavailable(Exception):
    pass


def _decode(value: str) -> bytes | None:
    try:
        raw = base64.urlsafe_b64decode(value.strip() + '=' * (-len(value.strip()) % 4))
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 32 else None


def _keys() -> list[bytes]:
    keys = []
    for name in ('TOKEN_ENCRYPTION_KEY', 'TOKEN_ENCRYPTION_KEY_OLD'):
        value = os.getenv(name, '')
        if value:
            key = _decode(value)
            if key:
                keys.append(key)
    return keys


def available() -> bool:
    return bool(os.getenv('TOKEN_ENCRYPTION_KEY')) and _decode(os.getenv('TOKEN_ENCRYPTION_KEY', '')) is not None


def generate_key() -> str:
    """A fresh 256-bit key in the format TOKEN_ENCRYPTION_KEY expects (for provisioning scripts)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')


def _table():
    with s.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS vault (name TEXT PRIMARY KEY, blob BLOB NOT NULL, created TEXT NOT NULL)')


def _aad(name: str) -> bytes:
    # Binds the ciphertext to its slot, so a blob copied into another slot does not decrypt.
    return VERSION + b':' + name.encode()


def put(name: str, value: str) -> None:
    if not available():
        raise VaultUnavailable('TOKEN_ENCRYPTION_KEY missing or invalid; refusing to store a secret')
    key = _keys()[0]
    nonce = secrets.token_bytes(12)
    blob = VERSION + nonce + AESGCM(key).encrypt(nonce, value.encode(), _aad(name))
    _table()
    with s.connect() as db:
        db.execute('INSERT OR REPLACE INTO vault VALUES(?,?,?)', (name, blob, s.utcnow()))


def get(name: str) -> str | None:
    _table()
    rows = s.rows('SELECT blob FROM vault WHERE name=?', (name,))
    if not rows:
        return None
    blob = bytes(rows[0]['blob'])
    if not blob.startswith(VERSION) or len(blob) < 2 + 12 + 16:
        return None
    nonce, data = blob[2:14], blob[14:]
    for i, key in enumerate(_keys()):
        try:
            value = AESGCM(key).decrypt(nonce, data, _aad(name)).decode()
        except InvalidTag:
            continue
        if i > 0 and available():
            put(name, value)  # transparent re-encryption after key rotation
        return value
    return None


def has(name: str) -> bool:
    _table()
    return bool(s.rows('SELECT 1 FROM vault WHERE name=?', (name,)))


def delete(name: str) -> None:
    _table()
    with s.connect() as db:
        db.execute('DELETE FROM vault WHERE name=?', (name,))
