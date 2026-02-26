# tests/test_daemon_http.py
import json
import threading
import urllib.request
import socketserver
import pytest
from jt import daemon, state


@pytest.fixture
def http_server(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'STATE_FILE', tmp_path / 'jt-state.json')
    state.write_state('houseofjawn', {'main': {'name': 'main', 'status': 'active'}})

    with socketserver.TCPServer(('', 0), None) as s:
        port = s.server_address[1]

    server = daemon._make_http_server(port)
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
