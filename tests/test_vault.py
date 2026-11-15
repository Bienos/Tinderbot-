import pytest
from agent import vault

TOKEN='50aa0000-1111-2222-3333-444455556666'


@pytest.fixture
def key(monkeypatch):
    k=vault.generate_key();monkeypatch.setenv('TOKEN_ENCRYPTION_KEY',k);monkeypatch.delenv('TOKEN_ENCRYPTION_KEY_OLD',raising=False);return k


def test_roundtrip_and_no_plaintext_on_disk(store,key):
    from agent import storage as s
    vault.put('tinder_token',TOKEN)
    assert vault.get('tinder_token')==TOKEN
    assert TOKEN.encode() not in s.DB_PATH.read_bytes()


def test_fails_closed_without_key(store,monkeypatch):
    monkeypatch.delenv('TOKEN_ENCRYPTION_KEY',raising=False)
    with pytest.raises(vault.VaultUnavailable):vault.put('tinder_token',TOKEN)
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY','too-short')
    assert not vault.available()
    with pytest.raises(vault.VaultUnavailable):vault.put('tinder_token',TOKEN)


def test_other_instance_key_cannot_decrypt(store,key,monkeypatch):
    vault.put('tinder_token',TOKEN)
    monkeypatch.setenv('TOKEN_ENCRYPTION_KEY',vault.generate_key())
    assert vault.get('tinder_token') is None


def test_blob_bound_to_its_slot(store,key):
    from agent import storage as s
    vault.put('tinder_token',TOKEN)
    blob=s.rows("SELECT blob FROM vault WHERE name='tinder_token'")[0]['blob']
    with s.connect() as db:db.execute("INSERT INTO vault VALUES('other',?,'x')",(blob,))
    assert vault.get('other') is None


def test_key_rotation_reencrypts(store,key,monkeypatch):
    vault.put('tinder_token',TOKEN)
    new=vault.generate_key();monkeypatch.setenv('TOKEN_ENCRYPTION_KEY',new);monkeypatch.setenv('TOKEN_ENCRYPTION_KEY_OLD',key)
    assert vault.get('tinder_token')==TOKEN
    monkeypatch.delenv('TOKEN_ENCRYPTION_KEY_OLD')
    assert vault.get('tinder_token')==TOKEN


def test_vault_token_wins_over_env_and_enables_tinder(store,key,monkeypatch):
    from agent import tinder
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.setenv('TINDER_AUTH_TOKEN','env-token-value-0000')
    assert tinder.token_source()=='env'
    vault.put(tinder.TOKEN_SLOT,TOKEN)
    assert tinder.token()==TOKEN and tinder.token_source()=='vault' and tinder.configured()
    status=tinder.public_status()
    assert status['token_source']=='vault' and TOKEN not in str(status)


class FakeClient:
    result='ok'
    def __init__(self,value):self.value=value;self.reconnect=False
    async def __aenter__(self):return self
    async def __aexit__(self,*a):pass
    async def profile(self):
        from agent.tinder import TinderAuthError
        if FakeClient.result=='denied':raise TinderAuthError('session_expired_or_access_denied')
        return 'owner'
    async def check_inbox_access(self):return None


def call(app_module,payload):
    import asyncio,json
    from starlette.requests import Request
    async def receive():return {'type':'http.request','body':json.dumps(payload).encode()}
    req=Request({'type':'http','method':'POST','path':'/api/tinder/token','headers':[]},receive)
    return asyncio.run(app_module.tinder_token_save(req))


def test_endpoint_verifies_then_stores_encrypted_and_never_echoes(store,key,monkeypatch):
    import app as application
    from agent import tinder
    from fastapi import HTTPException
    monkeypatch.setenv('TINDER_ENABLED','true');monkeypatch.delenv('TINDER_AUTH_TOKEN',raising=False)
    monkeypatch.setattr(tinder,'TinderClient',FakeClient)
    async def fake_connect():return 'tinder:owner'
    monkeypatch.setattr(tinder,'connect',fake_connect)
    application._TOKEN_ATTEMPTS.clear()
    with pytest.raises(HTTPException) as e:call(application,{'token':TOKEN})
    assert e.value.status_code==422
    FakeClient.result='denied'
    with pytest.raises(HTTPException) as e:call(application,{'token':TOKEN,'account_owned':True,'acknowledge_unofficial':True})
    assert e.value.status_code==403 and not vault.has(tinder.TOKEN_SLOT)
    FakeClient.result='ok'
    out=call(application,{'token':' "'+TOKEN+'" ','account_owned':True,'acknowledge_unofficial':True})
    assert out=={'connected':True,'connection_id':'tinder:owner'} and TOKEN not in str(out)
    assert vault.get(tinder.TOKEN_SLOT)==TOKEN
    import asyncio
    asyncio.run(application.tinder_token_delete())
    assert not vault.has(tinder.TOKEN_SLOT)


def test_endpoint_refuses_without_key(store,monkeypatch):
    import app as application
    from fastapi import HTTPException
    monkeypatch.delenv('TOKEN_ENCRYPTION_KEY',raising=False);application._TOKEN_ATTEMPTS.clear()
    with pytest.raises(HTTPException) as e:call(application,{'token':TOKEN,'account_owned':True,'acknowledge_unofficial':True})
    assert e.value.status_code==503
