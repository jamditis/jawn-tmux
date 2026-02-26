# tests/test_state.py
import json
from pathlib import Path
import pytest
from jt import state


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, 'STATE_FILE', tmp_path / 'jt-state.json')


def test_read_state_returns_empty_when_missing():
    assert state.read_state() == {}


def test_read_state_returns_empty_on_bad_json(tmp_path, monkeypatch):
    f = tmp_path / 'jt-state.json'
    monkeypatch.setattr(state, 'STATE_FILE', f)
    f.write_text('not json')
    assert state.read_state() == {}


def test_write_then_read_roundtrip():
    sessions = {'main': {'name': 'main', 'status': 'active'}}
    state.write_state('houseofjawn', sessions)
    result = state.read_state()
    assert result['node'] == 'houseofjawn'
    assert result['sessions'] == sessions
    assert 'updated_at' in result


def test_write_is_atomic(tmp_path, monkeypatch):
    f = tmp_path / 'jt-state.json'
    monkeypatch.setattr(state, 'STATE_FILE', f)
    state.write_state('houseofjawn', {})
    assert not (tmp_path / 'jt-state.tmp').exists()
    assert f.exists()
