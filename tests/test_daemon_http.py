# tests/test_daemon_http.py
import json
import threading
import urllib.request
import pytest
from jt import daemon, state


@pytest.fixture
def http_server(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'STATE_FILE', tmp_path / 'jt-state.json')
    state.write_state('houseofjawn', {'main': {'name': 'main', 'status': 'active'}})

    server = daemon._make_http_server(0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield port
    server.shutdown()


def test_status_endpoint_returns_state(http_server):
    url = f'http://127.0.0.1:{http_server}/status'
    with urllib.request.urlopen(url, timeout=2) as resp:
        data = json.loads(resp.read())
    assert data['node'] == 'houseofjawn'
    assert 'main' in data['sessions']


def test_unknown_path_returns_404(http_server):
    import urllib.error
    url = f'http://127.0.0.1:{http_server}/unknown'
    try:
        urllib.request.urlopen(url, timeout=2)
        assert False, 'should have raised'
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_default_bind_is_localhost():
    server = daemon._make_http_server(0)
    try:
        host = server.server_address[0]
    finally:
        server.server_close()
    # Must default to a loopback bind so agent stdout doesn't leak to the
    # network without explicit opt-in via JT_BIND.
    assert host in ('127.0.0.1', '::1', 'localhost')


def test_bind_argument_overrides_default():
    server = daemon._make_http_server(0, host='127.0.0.1')
    try:
        assert server.server_address[0] == '127.0.0.1'
    finally:
        server.server_close()


def test_status_endpoint_serves_concurrent_requests(http_server):
    # ThreadingHTTPServer: two slow-ish requests should overlap rather than
    # serialize. We just sanity check that two simultaneous requests both
    # succeed.
    import concurrent.futures

    def hit():
        url = f'http://127.0.0.1:{http_server}/status'
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: hit(), range(4)))
    assert results == [200, 200, 200, 200]
