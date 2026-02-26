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
