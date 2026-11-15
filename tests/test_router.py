"""The panel front door routes only well-formed customer hostnames and never echoes anything back."""
import http.client
import importlib
import os
import sys
import threading
from pathlib import Path

import pytest


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setenv('PUBLIC_DOMAIN', 'app.winq.site');monkeypatch.setenv('APP_PREFIX', 'winq-b-')
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'deploy' / 'router'))
    import router as r
    importlib.reload(r)
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer(('127.0.0.1', 0), r.Router)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    def call(host, path='/', method='GET', headers=None):
        c = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
        c.request(method, path, body=b'{"a":1}' if method == 'POST' else None, headers={'Host': host, **(headers or {})})
        resp = c.getresponse();resp.read();return resp
    yield call
    server.shutdown();sys.path.pop(0)


def test_customer_hostname_is_replayed_to_its_own_bot(router):
    r = router('k7f3p2ab.app.winq.site', '/auth/sso?t=secret')
    assert r.status == 204 and r.getheader('fly-replay') == 'app=winq-b-k7f3p2ab;timeout=15s;fallback=force_self'
    assert router('K7F3P2AB.App.Winq.Site:443', '/', 'POST').getheader('fly-replay').startswith('app=winq-b-k7f3p2ab;')


@pytest.mark.parametrize('host', ['app.winq.site', 'winq.site', 'evil.com', 'k7f3p2ab.app.winq.site.evil.com', 'a.app.winq.site',
                                  'k7-f3.app.winq.site', 'x.k7f3p2ab.app.winq.site', '../router.app.winq.site', ''])
def test_anything_else_is_not_routed(router, host):
    r = router(host)
    assert r.status == 404 and r.getheader('fly-replay') is None


def test_failed_replay_shows_a_friendly_page_and_health_is_local(router):
    assert router('k7f3p2ab.app.winq.site', headers={'fly-replay-failed': 'app=winq-b-k7f3p2ab'}).status == 503
    r = router('winq-router.internal', '/healthz')
    assert r.status == 200 and r.getheader('fly-replay') is None
