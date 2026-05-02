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


def test_write_state_creates_parent_dir(tmp_path, monkeypatch):
    f = tmp_path / 'nested' / 'dir' / 'jt-state.json'
    monkeypatch.setattr(state, 'STATE_FILE', f)
    state.write_state('houseofjawn', {})
    assert f.exists()


def test_write_state_uses_mode_0600(tmp_path, monkeypatch):
    import stat
    f = tmp_path / 'jt-state.json'
    monkeypatch.setattr(state, 'STATE_FILE', f)
    state.write_state('houseofjawn', {})
    mode = stat.S_IMODE(f.stat().st_mode)
    # output_tail can leak agent stdout — file must be private to the user.
    assert mode == 0o600, f'expected 0600, got {oct(mode)}'


def test_default_state_file_prefers_jt_state_file_env(tmp_path, monkeypatch):
    monkeypatch.setenv('JT_STATE_FILE', str(tmp_path / 'override.json'))
    monkeypatch.delenv('XDG_RUNTIME_DIR', raising=False)
    assert state._default_state_file() == tmp_path / 'override.json'


def test_default_state_file_falls_back_to_xdg_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.delenv('JT_STATE_FILE', raising=False)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    assert state._default_state_file() == tmp_path / 'jt-state.json'


def test_default_state_file_falls_back_to_tmp(monkeypatch):
    monkeypatch.delenv('JT_STATE_FILE', raising=False)
    monkeypatch.delenv('XDG_RUNTIME_DIR', raising=False)
    from pathlib import Path
    assert state._default_state_file() == Path('/tmp/jt-state.json')
