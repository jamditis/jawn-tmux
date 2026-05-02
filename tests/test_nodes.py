# tests/test_nodes.py
import json
from unittest.mock import patch, MagicMock
import pytest
from jt import nodes


@pytest.fixture
def nodes_config(tmp_path, monkeypatch):
    cfg = tmp_path / 'nodes.json'
    cfg.write_text(json.dumps([
        {'name': 'houseofjawn', 'ip': '100.122.208.15', 'port': 6248},
        {'name': 'officejawn',  'ip': '100.84.214.24',  'port': 6248},
    ]))
    monkeypatch.setattr(nodes, 'NODES_FILE', cfg)


def test_load_nodes_returns_list(nodes_config):
    result = nodes.load_nodes()
    assert len(result) == 2
    assert result[0]['name'] == 'houseofjawn'


def test_load_nodes_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes, 'NODES_FILE', tmp_path / 'missing.json')
    assert nodes.load_nodes() == []


def test_fetch_remote_state_returns_dict():
    fake_state = {'node': 'officejawn', 'sessions': {}}
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(fake_state).encode()

    with patch('urllib.request.urlopen', return_value=mock_resp):
        result = nodes.fetch_remote_state({'name': 'officejawn', 'ip': '1.2.3.4', 'port': 6248})
    assert result == fake_state


def test_fetch_remote_state_returns_none_on_failure():
    with patch('urllib.request.urlopen', side_effect=Exception('timeout')):
        result = nodes.fetch_remote_state({'name': 'officejawn', 'ip': '1.2.3.4', 'port': 6248})
    assert result is None


def test_load_nodes_returns_empty_for_non_list_json(tmp_path, monkeypatch):
    cfg = tmp_path / 'nodes.json'
    cfg.write_text('{}')
    monkeypatch.setattr(nodes, 'NODES_FILE', cfg)
    assert nodes.load_nodes() == []


def test_fetch_remote_state_returns_none_on_missing_ip():
    result = nodes.fetch_remote_state({'name': 'test', 'port': 6248})
    assert result is None


def test_fetch_remote_state_uses_default_port_for_null_port():
    fake_state = {'node': 'test', 'sessions': {}}
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = json.dumps(fake_state).encode()

    captured_urls = []
    def capture_urlopen(url, timeout):
        captured_urls.append(url)
        return mock_resp

    with patch('urllib.request.urlopen', side_effect=capture_urlopen):
        result = nodes.fetch_remote_state({'name': 'test', 'ip': '1.2.3.4', 'port': None})
    assert result == fake_state
    assert f':{nodes.DEFAULT_PORT}/' in captured_urls[0]


def test_fetch_remotes_runs_concurrently_and_preserves_order():
    import threading
    import time

    barrier = threading.Barrier(3)

    def fake_fetch(node, timeout=None):
        # Block until all three fetchers reach this point. If the
        # implementation is serial we'll deadlock — pytest will time out and
        # fail clearly.
        barrier.wait(timeout=2)
        time.sleep(0.01)
        return {'node': node['name'], 'sessions': {}}

    inputs = [
        {'name': 'a', 'ip': '1.1.1.1'},
        {'name': 'b', 'ip': '2.2.2.2'},
        {'name': 'c', 'ip': '3.3.3.3'},
    ]
    with patch.object(nodes, 'fetch_remote_state', side_effect=fake_fetch):
        results = nodes.fetch_remotes(inputs)

    assert [n['name'] for n, _ in results] == ['a', 'b', 'c']
    assert [r['node'] for _, r in results] == ['a', 'b', 'c']


def test_fetch_remotes_empty_returns_empty_list():
    assert nodes.fetch_remotes([]) == []
