"""Safe failure references and opt-in read-only checks, using synthetic credentials."""
import json
import re

from fastapi.testclient import TestClient

from agent import diagnostics, runtime as rt, storage as s, tinder


def test_unexpected_connect_error_has_safe_reference_and_durable_activity(store, monkeypatch, capsys):
    from app import app
    secret = 'synthetic-token-and-private-message-do-not-log'
    async def fail():
        raise RuntimeError(secret)
    monkeypatch.setattr(tinder, 'connect', fail)
    with TestClient(app, headers={'Authorization': 'Bearer test-dashboard-token-at-least-32-chars'}) as client:
        response = client.post('/api/tinder/connect', json={'account_owned': True, 'acknowledge_unofficial': True})
        assert response.status_code == 500
        reference = response.json()['error_id']
        assert re.fullmatch(r'[a-f0-9]{16}', reference)
        assert reference in response.json()['detail']
        assert client.get('/api/state').status_code == 200
    logs = capsys.readouterr().out
    assert secret not in logs + response.text + json.dumps(s.rows('SELECT * FROM activity'))
    metadata = next(json.loads(line) for line in logs.splitlines() if 'exception_type' in line)
    assert metadata['operation'] == '/api/tinder/connect' and metadata['exception_type'] == 'RuntimeError'
    assert metadata['frames'][-1]['function'] == 'fail'
    assert any(reference in row['detail'] for row in s.rows('SELECT * FROM activity'))


def test_error_logging_survives_unavailable_database(store, monkeypatch, capsys):
    monkeypatch.setattr(rt, 'audit', lambda *a: (_ for _ in ()).throw(OSError('synthetic DB failure')))
    try:
        raise ValueError('do-not-log-this-value')
    except ValueError as exc:
        reference = diagnostics.report_failure(exc, 'test_operation')
    metadata = json.loads(capsys.readouterr().out)
    assert metadata['reference'] == reference and metadata['exception_type'] == 'ValueError'
    assert 'do-not-log-this-value' not in json.dumps(metadata)


async def test_tinder_preflight_reads_profile_without_enabling_or_sending(store, monkeypatch, capsys):
    calls = []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def profile(self): calls.append('profile'); return 'private-owner-id'
    monkeypatch.setattr(tinder, 'configured', lambda: True)
    monkeypatch.setattr(tinder, 'client', Client)
    await diagnostics.tinder_startup_check()
    assert calls == ['profile']
    assert not s.rows('SELECT * FROM connections') and not s.rows('SELECT * FROM actions')
    logs = capsys.readouterr().out
    assert json.loads(logs) == {'event': 'tinder_preflight', 'state': 'ok'}
    assert 'private-owner-id' not in logs


async def test_tinder_preflight_rejection_is_controlled_and_unknown_details_are_redacted(store, monkeypatch, capsys):
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def profile(self): raise tinder.TinderAuthError('unexpected-private-token')
    monkeypatch.setattr(tinder, 'configured', lambda: True)
    monkeypatch.setattr(tinder, 'client', Client)
    await diagnostics.tinder_startup_check()
    logs = capsys.readouterr().out
    assert 'unexpected-private-token' not in logs
    assert json.loads(logs)['code'] == 'tinder_request_failed'


async def test_tinder_preflight_unexpected_error_logs_metadata_only(store, monkeypatch, capsys):
    monkeypatch.setattr(tinder, 'configured', lambda: True)
    def fail(): raise TypeError('synthetic-private-value')
    monkeypatch.setattr(tinder, 'client', fail)
    await diagnostics.tinder_startup_check()
    logs = capsys.readouterr().out
    assert 'synthetic-private-value' not in logs and 'TypeError' in logs
    assert not s.rows('SELECT * FROM connections')


async def test_tinder_preflight_respects_global_pause(store, monkeypatch, capsys):
    cfg = rt.settings(); cfg['paused'] = True; rt.save_settings(cfg)
    capsys.readouterr()
    monkeypatch.setattr(tinder, 'configured', lambda: True)
    monkeypatch.setattr(tinder, 'client', lambda: (_ for _ in ()).throw(AssertionError('Should not request')))
    await diagnostics.tinder_startup_check()
    assert json.loads(capsys.readouterr().out)['state'] == 'paused'
